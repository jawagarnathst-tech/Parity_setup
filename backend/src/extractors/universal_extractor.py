import pdfplumber
import os
import re
from openai import OpenAI
from src.schemas.master_schema import MasterSBCSchema
from src.extractors.text_cleaner import TextCleaner
from src.extractors.ocr_helper import ocr_pdf_header, ocr_image, ocr_pdf_full
try:
    import docx
except ImportError:
    docx = None

class UniversalExtractor:
    def __init__(self):
        # Initialize OpenAI client with extended timeouts to handle network issues
        self.client = OpenAI(
            timeout=120.0,  # 120 second timeout for API calls
            max_retries=3   # Retry up to 3 times on failure
        )
        self.cleaner = TextCleaner()

    def _extract_in_network_value(self, raw_value: str) -> str:
        if raw_value is None:
            return None
        raw_value = raw_value.strip()
        if raw_value == "":
            return None

        # Prefer explicit In-Network values if both In-Network and Out-of-Network values are present.
        in_network_match = re.search(
            r'(?:In[- ]Network|In Network|In-Network)\s*[:\-]?\s*([^;|\n]+)',
            raw_value,
            re.IGNORECASE,
        )
        if in_network_match:
            return in_network_match.group(1).strip()

        if re.search(r'Out[- ]?of[- ]?Network', raw_value, re.IGNORECASE):
            # Prefer text before the out-of-network section if it appears first.
            parts = re.split(r'Out[- ]?of[- ]?Network', raw_value, flags=re.IGNORECASE)
            if parts and parts[0].strip():
                return parts[0].strip()

        return raw_value

    def _normalize_pharmacy_tier(self, raw_value: str) -> str:
        if raw_value is None:
            return None
        raw_value = raw_value.strip()
        if raw_value == "":
            return None

        raw_value_lower = raw_value.lower()
        if 'no charge' in raw_value_lower or 'not applicable' in raw_value_lower:
            return '$0'

        raw_value = self._extract_in_network_value(raw_value)

        # Prefer the retail value if both retail and mail-order values are present.
        parts = re.split(r';|\band\b|\bor\b|\|', raw_value, flags=re.IGNORECASE)
        retail_part = None
        fallback_part = None
        for part in parts:
            part_text = part.strip()
            part_lower = part_text.lower()
            if 'retail' in part_lower and 'mail' not in part_lower:
                retail_part = part_text
                break
            if fallback_part is None and 'mail' not in part_lower:
                fallback_part = part_text
        if retail_part:
            raw_value = retail_part
        elif fallback_part:
            raw_value = fallback_part

        # Remove descriptive parentheticals like (retail) or (mail order)
        raw_value = re.sub(r'\s*\([^)]*\)', '', raw_value).strip()

        # If there is a direct dollar amount, return only that
        dollar_match = re.search(r'\$[\d,]+(?:\.\d+)?', raw_value)
        if dollar_match:
            return dollar_match.group(0)

        # Preserve simple percentage expressions when there is no dollar amount
        percent_match = re.search(r'\d+%', raw_value)
        if percent_match:
            return percent_match.group(0)

        return raw_value

    def _percent_near_keyword(self, text: str, keyword_pattern: str, window: int = 80) -> bool:
        """Return True if a percentage (e.g. '20%') or the word 'percent' appears
        within `window` characters of any occurrence of `keyword_pattern` in text.
        This helps avoid assigning a coinsurance value to a visit row when the
        percent actually refers to nearby imaging/facility rows.
        """
        if not text:
            return False
        flags = re.IGNORECASE
        for m in re.finditer(keyword_pattern, text, flags):
            start, end = m.start(), m.end()
            lo = max(0, start - window)
            hi = min(len(text), end + window)
            snippet = text[lo:hi]
            if re.search(r'\d+%|percent', snippet, flags):
                return True
        return False

    def _needs_ocr_header(self, raw_text: str) -> bool:
        # If the text contains a header line beginning with a leading colon, the carrier prefix may be missing.
        if re.search(r'^\s*:\s*[^\n]+Plan Type:', raw_text, re.IGNORECASE | re.MULTILINE):
            return True

        lines = [line for line in raw_text.splitlines() if line.strip()]
        if len(lines) >= 2 and re.match(r'^\s*:\s*', lines[1]):
            return True

        return False

    def _format_ocr_snippet(self, ocr_text: str, max_length: int = 180) -> str:
        snippet = ' '.join(ocr_text.split())
        if len(snippet) > max_length:
            snippet = snippet[:max_length].rstrip() + '...'
        return snippet

    def _extract_plan_name_from_text(self, raw_text: str, extracted_name: str, extracted_carrier: str) -> str:
        candidate = extracted_name

        def is_date_range(text: str) -> bool:
            return bool(re.search(r'\d{1,2}/\d{1,2}/\d{2,4}\s*-\s*\d{1,2}/\d{1,2}/\d{2,4}', text))

        def clean_metadata(text: str) -> str:
            """Clean common metadata labels out of the plan name candidate."""
            t = re.sub(r'Coverage for:.*', '', text, flags=re.IGNORECASE)
            t = re.sub(r'Plan Type:.*', '', t, flags=re.IGNORECASE)
            t = re.sub(r'Summary of Benefits.*', '', t, flags=re.IGNORECASE)
            return t.strip(' |,-/\t')

        def strip_page_marker(text: str) -> str:
            return re.sub(r'^---\s*PAGE\s*\d+\s*(?:TEXT|STRUCTURED).*?--+\s*', '', text, flags=re.IGNORECASE).strip()

        plan_name = None
        lines = raw_text.splitlines()

        # ── Priority 0: UnitedHealthcare Specific Pattern ─────────────────────
        # Look for "SBC_filename" pattern or title line with plan details
        # Examples: "SBC_120-25_UnitedHealthcare_Choice_Plus_HDHP_3300"
        #           "UnitedHealthcare Choice Plus HDHP 3300"
        # ────────────────────────────────────────────────────────────────────────
        
        # First try: filename pattern in header
        uhc_filename_pattern = re.search(
            r'SBC[_\-]\d+[_\-]\d+[_\-]UnitedHealthcare[_\s]*([A-Za-z0-9\s_]+?)(?:\s+\d+)?(?:\.pdf)?',
            raw_text, 
            re.IGNORECASE
        )
        if uhc_filename_pattern:
            uhc_candidate = uhc_filename_pattern.group(1).strip()
            # Clean up underscores and normalize spaces
            uhc_candidate = re.sub(r'[_]+', ' ', uhc_candidate).strip()
            uhc_candidate = re.sub(r'\s+', ' ', uhc_candidate)
            # Remove trailing page numbers
            uhc_candidate = re.sub(r'\s+\d+\s*$', '', uhc_candidate).strip()
            if uhc_candidate and len(uhc_candidate) > 3:
                plan_name = f"UnitedHealthcare {uhc_candidate}"
                print(f"    [PLAN_NAME] UHC filename pattern found: {plan_name}")

        # Second try: direct text line pattern  
        if not plan_name:
            uhc_direct_pattern = re.search(
                r'UnitedHealthcare\s+([A-Za-z0-9\s]+(?:HDHP|PPO|HMO|Choice|Options)[A-Za-z0-9\s]*)',
                raw_text, 
                re.IGNORECASE
            )
            if uhc_direct_pattern:
                uhc_candidate = uhc_direct_pattern.group(1).strip()
                uhc_candidate = re.sub(r'\s+', ' ', uhc_candidate)
                # Remove trailing page numbers or artifacts
                uhc_candidate = re.sub(r'\s+\d+\s*$', '', uhc_candidate).strip()
                if uhc_candidate and len(uhc_candidate) > 3:
                    plan_name = f"UnitedHealthcare {uhc_candidate}"
                    print(f"    [PLAN_NAME] UHC direct pattern found: {plan_name}")

        # ── Priority 1 ─────────────────────────────────────────────────────────
        # Find the SBC header line containing BOTH "Coverage for:" and "Plan Type:".
        #
        #   Pattern A (Cigna):  GALA CORPORATION: $3,000 COPAY Coverage for: Ind/Family | Plan Type: PPO
        #                       → extract text between employer colon and "Coverage for:"
        #
        #   Pattern B (WellMark): Coverage for: Single & Family | Plan Type: PPO
        #                         EnhancedBlueSM 1500 PPO   ← plan name on NEXT line
        # ────────────────────────────────────────────────────────────────────────
        if not plan_name:
            for idx, line in enumerate(lines):
                if 'coverage for:' in line.lower() and 'plan type:' in line.lower():

                    # --- Pattern A: text BEFORE "Coverage for:" on this same line ---
                    before_cov = re.split(r'Coverage for:', line, maxsplit=1, flags=re.IGNORECASE)[0].strip()
                    before_cov = strip_page_marker(before_cov)
                    before_cov = re.sub(r'^Summary of Benefits[^:]*:?', '', before_cov, flags=re.IGNORECASE).strip()
                    before_cov = re.sub(r'Coverage Period\s*:.*$', '', before_cov, flags=re.IGNORECASE).strip(' |,-/\t')

                    if ':' in before_cov:
                        # "EMPLOYER_NAME: PLAN_NAME" → take part after the LAST colon
                        after_colon = before_cov.rsplit(':', 1)[1].strip()
                        cleaned = clean_metadata(after_colon)
                        if cleaned and len(cleaned) > 2 and not is_date_range(cleaned):
                            plan_name = cleaned

                    # --- Pattern B: plan name on the NEXT non-metadata line ---
                    if not plan_name:
                        skip_phrases = [
                            'coverage for:', 'plan type:', 'summary of benefits',
                            'the summary of', 'this is only a summary', 'share the cost',
                            'note:', 'important questions', 'what is the overall',
                            '1-800', '1-888', 'all copayment', 'all coinsurance',
                        ]
                        for next_line in lines[idx + 1:idx + 6]:
                            nl_clean = next_line.strip()
                            if not nl_clean:
                                continue
                            if any(kw in nl_clean.lower() for kw in skip_phrases):
                                continue
                            if is_date_range(nl_clean):
                                continue
                            nl_clean = strip_page_marker(nl_clean)
                            cleaned = clean_metadata(nl_clean)
                            if cleaned and len(cleaned) > 3:
                                plan_name = cleaned
                                break
                    break  # Only check the first occurrence of this header line

        # ── Priority 2 ─────────────────────────────────────────────────────────
        # Text BEFORE "Coverage Period:" on the same line (e.g., "BlueOptions 05906 Coverage Period:...")
        # ────────────────────────────────────────────────────────────────────────
        if not plan_name:
            pre_coverage_match = re.search(r'^\s*(.*?)\s*Coverage Period:', raw_text, re.IGNORECASE | re.MULTILINE)
            if pre_coverage_match:
                pc_candidate = strip_page_marker(pre_coverage_match.group(1).strip())
                cleaned = clean_metadata(pc_candidate)
                if cleaned and len(cleaned) > 3 and not is_date_range(cleaned):
                    plan_name = cleaned

        # ── Priority 3 ─────────────────────────────────────────────────────────
        # Lines AFTER "Coverage Period:" — 8-line lookahead to reach past metadata lines.
        # ────────────────────────────────────────────────────────────────────────
        if not plan_name:
            for idx, line in enumerate(lines):
                if 'coverage period:' in line.lower():
                    for next_line in lines[idx + 1:idx + 8]:
                        nl_clean = next_line.strip()
                        if not nl_clean:
                            continue
                        nl_lower = nl_clean.lower()
                        if 'coverage for:' in nl_lower or 'plan type:' in nl_lower or 'summary of benefits' in nl_lower:
                            continue
                        if is_date_range(nl_clean):
                            continue
                        nl_clean = strip_page_marker(nl_clean)
                        cleaned = clean_metadata(nl_clean)
                        if cleaned and len(cleaned) > 3:
                            plan_name = cleaned
                            break
                    break

        # ── Standardize LLM candidate ───────────────────────────────────────────
        # Reject if clearly not a plan name (too long or contains known bad phrases).
        BAD_PHRASES = [
            'your rights', 'there are agencies', 'contact information', 'this is only a summary',
            'welcometouhc.com', 'for general definitions', 'allowed amount', 'balance billing',
            'coinsurance, copayment', 'underlined terms', 'see the glossary'
        ]
        if candidate:
            candidate = clean_metadata(candidate.strip())
            if (is_date_range(candidate)
                    or candidate.lower() == extracted_carrier.strip().lower()
                    or candidate.lower() == 'plan'
                    or len(candidate.split()) > 12
                    or any(p in candidate.lower() for p in BAD_PHRASES)):
                candidate = None
                print(f"    [PLAN_NAME] Rejected LLM candidate: contains bad phrases or invalid format")

        if plan_name and is_date_range(plan_name):
            plan_name = None

        if candidate and plan_name:
            # Prefer regex-detected plan_name if LLM candidate is shorter/less specific
            if len(candidate.split()) < max(4, len(plan_name.split())):
                print(f"    [PLAN_NAME] Using regex result: {plan_name}")
                return plan_name
            print(f"    [PLAN_NAME] Using LLM result: {candidate}")
            return candidate

        final_name = candidate or plan_name or extracted_carrier
        print(f"    [PLAN_NAME] Final result: {final_name}")
        return final_name

    def _extract_pdf(self, file_path: str) -> str:
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text()
                if t:
                    text += f"--- PAGE {i+1} TEXT ---\n" + t + "\n"
                
                tables = page.extract_tables()
                if tables:
                    text += f"--- PAGE {i+1} STRUCTURED TABLES ---\n"
                    for table in tables:
                        for row in table:
                            clean_row = [str(cell).replace('\n', ' ').strip() if cell else '' for cell in row]
                            text += " | ".join(clean_row) + "\n"
                    text += "\n"

        # If extracted text is very short, it's likely a scanned PDF. Trigger full OCR.
        if len(text.strip()) < 150:
            print(f"  [OCR] Low text volume detected ({len(text)} chars). Attempting full OCR on {os.path.basename(file_path)}...")
            text = ocr_pdf_full(file_path)

        if self._needs_ocr_header(text):
            ocr_text = ocr_pdf_header(file_path)
            if ocr_text:
                snippet = self._format_ocr_snippet(ocr_text)
                print(f"  [OCR] Header fallback used; OCR snippet: {snippet}")
                text = ocr_text + "\n" + text
        return text

    def _extract_docx(self, file_path: str) -> str:
        if not docx:
            print("  [ERR] python-docx not installed. Skipping Word file.")
            return ""
        doc = docx.Document(file_path)
        text = ""
        for i, para in enumerate(doc.paragraphs):
            if para.text.strip():
                text += para.text + "\n"
        
        for i, table in enumerate(doc.tables):
            text += f"--- TABLE {i+1} STRUCTURED ---\n"
            for row in table.rows:
                row_text = [cell.text.replace('\n', ' ').strip() for cell in row.cells]
                text += " | ".join(row_text) + "\n"
            text += "\n"
        return text

    def _extract_image(self, file_path: str) -> str:
        print(f"  [OCR] Processing image {os.path.basename(file_path)}...")
        return ocr_image(file_path)

    def extract_text(self, file_path: str, save_raw_path: str = None, filename: str = None) -> MasterSBCSchema:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Could not find {file_path}")
        
        ext = os.path.splitext(file_path)[1].lower()
        text = ""
        
        if ext == '.pdf':
            text = self._extract_pdf(file_path)
        elif ext in ['.docx', '.doc']:
            text = self._extract_docx(file_path)
        elif ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff']:
            text = self._extract_image(file_path)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

        if not text.strip():
            raise ValueError(f"No text could be extracted from {file_path}")

        # Clean the raw text to remove noise before sending to AI
        text = self.cleaner.clean(text)

        # Save raw extracted text if path is provided
        if save_raw_path:
            os.makedirs(os.path.dirname(save_raw_path), exist_ok=True)
            with open(save_raw_path, 'w', encoding='utf-8') as f:
                f.write(f"=== RAW TEXT EXTRACTED FROM: {os.path.basename(file_path)} ===\n")
                f.write(f"=== Total characters: {len(text)} ===\n\n")
                f.write(text)
            print(f"[OK] Raw text saved: {save_raw_path}")

        FORMATTING_RULES = """
STRICT VALUE FORMATTING RULES - Follow these exactly:
1. DOLLAR VALUES: Keep the $ symbol. Strip all trailing words. Example: "$250 copay per visit" -> "$250". "$10 copay" -> "$10".
2. PERCENTAGE VALUES: Keep the % symbol. Strip all trailing words. Example: "20% coinsurance" -> "20%". "40% after deductible" -> "40%".
3. NO CHARGE: Convert "No Charge", "no charge", or "Not Applicable" to "$0".
4. PHARMACY DEDUCTIBLES with Individual/Family: Return ONLY the Individual value. Example: "$150 Individual/$450 Family" -> "$150".
5. MIXED DOLLAR+PERCENT (e.g. "$200 or 20%"): Return as-is: "$200 or 20%".
6. NOT COVERED: Return "Not Covered" as-is.
7. DO NOT include words like "copay", "coinsurance", "per visit", "per stay", "after deductible".
8. COINSURANCE FIELDS: These expect a % value. Example: "20% coinsurance" -> "20%".
9. COPAY FIELDS: These expect a $ value. Example: "$35 copay" -> "$35".
10. DEDUCTIBLE AND OOP MAX FIELDS (individual_deductible, family_deductible, individual_oop_max, family_oop_max): Keep the $ symbol and comma. Example: "$1,500".
11. 100% MINUS RULE (PATIENT RESPONSIBILITY): If the document lists what the PLAN pays for coinsurance (e.g., "Plan pays 80%", "Plan pays 70%"), or if any extracted coinsurance is between 60% and 100% (inclusive), you MUST subtract it from 100% to calculate the patient's responsibility. For example, if the document says "80%", extract it as "20%". If it says "70%", extract it as "30%". CRITICAL: The extracted coinsurance MUST be the PATIENT responsibility.

CRITICAL: COPAY vs COINSURANCE DETECTION RULES:
- IF the document shows ONLY percentage values (e.g., "10% coinsurance") for a service, put the percentage in COINSURANCE field and "$0" in COPAY field.
- IF the document shows ONLY dollar amounts (e.g., "$35 copay") for a service, put the dollar amount in COPAY field and "0%" in COINSURANCE field.
- IF the document shows BOTH (e.g., "$35 copay, 20% coinsurance"), extract BOTH values into their respective fields.
- IN-NETWORK FIRST PRIORITY: When a service shows two columns - "Participating Provider (In-Network)" and "Non-Participating Provider (Out-of-Network)" - ALWAYS extract from the IN-NETWORK column FIRST. The In-Network column is the correct/primary value. Example: If "Primary care" shows "No Charge/visit; deductible does not apply" in In-Network and "50% coinsurance" in Out-of-Network, extract ONLY "No Charge" from In-Network. Do NOT extract the Out-of-Network value.
- PIPE SEPARATED TABLES CAUTION: If the text uses pipe separators like "| $40 copayment | 40% coinsurance |", the pipes separate columns! The first column is In-Network and the second is Out-of-Network. You MUST COMPLETELY IGNORE the Out-of-Network value. In this example, extract "$40" for copay and "0%" for coinsurance. Do NOT extract the 40% coinsurance because it belongs to the Out-of-Network column.
- MULTI-COLUMN TABLES (3+ columns): CRITICAL - Some insurance documents (especially Anthem) have THREE columns: "Level 1 Pharmacy-Only", "In-Network Provider", and "Out-of-Network Provider". ALWAYS extract from the MIDDLE column labeled "In-Network Provider" or "In-Network". NEVER extract from "Level 1 Pharmacy" or "Out-of-Network" columns. Example: If a row shows "| $20 | $30 | $50 |" for "Level 1", "In-Network", and "Out-of-Network", extract ONLY $30 (the In-Network value). Do NOT extract $20 or $50.
- IF YOU SEE COINSURANCE IN BOTH COLUMNS (e.g., "| 20% | 45% |" where first is Level 1 and second is In-Network), extract ONLY the In-Network value (45%). This happens frequently in Anthem plans.
- NEVER put percentage values in copay fields or dollar values in coinsurance fields.

MODIFIER FIELD RULES:
11. MEDICAL MODIFIER FIELDS (e.g., primary_care_copay_modifier, inpatient_coinsurance_modifier): 
    - If text says "deductible does not apply", "deductible doesn't apply", or "no charge" → return "Deductible Waived"
    - If text says "after deductible" or shows deductible applies → return "After Deductible"  
    - Otherwise, return null
12. DEDUCTIBLE STATUS FIELDS (e.g., primary_care_copay_deductible_status, primary_care_coinsurance_deductible_status):
    - If the text explicitly says "deductible does not apply", "no charge", or "after deductible", extract that EXACT phrase into the deductible_status field. Otherwise return null.
13. PHARMACY MODIFIER FIELDS (e.g., tier_1_copay_modifier, tier_2_coinsurance_modifier): 
    - If text says "deductible does not apply" for that tier → return "Rx - Deductible Waived"
    - If text mentions "rx deductible" or "prescription deductible" → return "Rx - After Rx Deductible"
    - If text mentions "plan deductible" → return "Rx - After Plan Deductible"
    - Otherwise, return null

HOSPITAL SURGICAL EXTRACTION RULES (FACILITY-ONLY):
13. INPATIENT HOSPITAL COPAY & COINSURANCE: Extract ONLY from the "Facility" row (e.g., "Facility fee (e.g., ambulatory surgery center)" or "Facility fee (e.g., hospital room)") under the "If you have a hospital stay" section. Do NOT extract from "Physician/surgeon fees" row or any other non-facility rows. These values go into inpatient_copay and inpatient_coinsurance fields. CRITICAL: Only extract inpatient facility fees when the section is explicitly labeled for hospital/inpatient services. Do not extract facility fees from emergency care, urgent care, or other non-hospital sections.
14. OUTPATIENT HOSPITAL COPAY & COINSURANCE: Extract ONLY from the "Facility" row under the "If you have outpatient surgery" or "outpatient hospital" sections (e.g., "Facility fee (e.g., ambulatory surgery center)"). Do NOT extract from "Physician/surgeon fees" row or facility fees from emergency/urgent care sections. These values go into op_hospital_copay and op_hospital_coinsurance fields. CRITICAL: Facility fees for outpatient services must be from the outpatient surgery/hospital section ONLY, not from emergency or urgent care rows.
15. CRITICAL: Physician/surgeon fees are separate services and must NOT be confused with facility fees. Look for explicit "Facility" or "Facility fee" labels in the table row. If only physician/surgeon fees exist without facility fees, extract "$0" for facility-based fields. Do NOT extract facility fees from emergency medical transportation, emergency room, or urgent care sections even if they mention "facility" — these belong to different service categories and should not populate inpatient_copay, inpatient_coinsurance, op_hospital_copay, or op_hospital_coinsurance fields.

LAB AND X-RAY EXTRACTION RULES (SPLIT LAYOUT HANDLING):
15a. LAB AND X-RAY COINSURANCE: When Lab and X-ray appear on SEPARATE LINES with percentages like "Lab: 20% coinsurance" and "X-ray: 20% coinsurance", extract BOTH values from their respective lines. Do NOT treat them as missing values just because they appear on different lines from the "Diagnostic test" label. Look specifically for "Lab:" prefix followed by a percentage value, and "X-ray:" prefix followed by a percentage value. Extract from the IN-NETWORK column ONLY (ignore "Not Covered" or Out-of-Network values that appear after a pipe |). Examples: "Lab: 20% coinsurance | Not Covered" → extract 20% for lab_services_coinsurance. "X-ray: 20% coinsurance | Not Covered" → extract 20% for xray_coinsurance.

PHARMACY EXTRACTION RULES:
16. PHARMACY TIER VALUES: Use the "STRUCTURED TABLES" provided in the text for accurate column alignment. For pharmacy costs, there are often three columns: "Level 1 Pharmacy", "In-Network Provider", and "Out-of-Network". You MUST extract ONLY the "In-Network Provider" value for Tiers 1-4. In the structured tables, this is typically the 4th column. Do not extract the "Level 1" value (which is typically the 3rd column). If both retail and home delivery/mail order are present in that cell, extract ONLY the retail value.
17. PHARMACY TIER COMPLETENESS: You MUST extract ALL pharmacy tiers present in the document (typically Tiers 1-5). Do NOT skip any tier. If a tier row is present in the structured table, extract its value from the In-Network column. Common issue: Some extractors skip Tier 2 or Tier 3. CRITICAL: Count the tiers and ensure all are present in your output. Tiers with values like "$20/Rx", "$100/Rx", "$170/Rx", "40% coinsurance", "$500/Rx" must all be extracted.
18. MULTIPLE VALUES: If a service lists BOTH a copay AND a coinsurance (e.g., "$35 copayment 50% coinsurance"), you MUST extract both and place them into their respective fields. However, if they are separated by a pipe (e.g., "| $35 copay | 50% coinsurance |"), the second value is Out-of-Network and MUST BE IGNORED. Do not extract the Out-of-Network value.
19. SPECIALTY RX DESCRIPTION: This field captures specialty drug costs from the In-Network column ONLY. Look for specialty drug information in TWO possible formats:
    FORMAT A (Dedicated Specialty Row): Look for a dedicated "Specialty drugs" row in the pharmacy table (usually after Tier 3 or Tier 4). Extract the complete In-Network value including all information.
    FORMAT B (Inline Specialty): When specialty drugs appear inline with each tier (e.g., "Tier 3: Retail: $100 copay | Specialty Drugs: $350 copay"), extract and COMBINE all tier specialty values in order. Example: If Tier 1 has "Specialty: $5", Tier 2 has "Specialty: $150", Tier 3 has "Specialty: $350", Tier 4 has "Specialty: $500", extract as "$5/$150/$350/$500".
    In BOTH formats: Include BOTH percentages AND dollar amounts if both appear. Examples: If In-Network shows "30% (preferred), 50% (non-preferred)", extract as "30%/50%". If it shows "$300/$500", extract as-is. If it shows "Applicable cost as noted above for generic or brand drugs", "Same as above", or "Matches Previous Tiers", extract that exact phrase into specialty_rx_description AND set specialty_mirrors_tiers_1_3 to true. 
    CRITICAL: If NO specialty drug information exists anywhere in the document, set specialty_rx_description to null (do NOT default to "$0" or use the deductible amount). Extract ONLY from In-Network column, NEVER from Out-of-Network or Limitations columns. NEVER put specialty cost into tier_4_copay or tier_5_copay fields - it belongs ONLY in specialty_rx_description. Do not overwrite or remove existing copay/coinsurance values from Tiers 1-5; they must coexist with the specialty drug values.

BOOLEAN AND IDENTIFICATION RULES:
20. BOOLEAN FIELDS: For HDHP, Open Access, Offers Tier 1A Benefit, Specialty Mirrors Tiers 1-3, and Out Of Network Coverage, return true or false.
21. BLANK OR MISSING VALUES: If a service is not mentioned or is completely blank for a specific field:
    - For COINSURANCE fields: return "0%".
    - For COPAY, DEDUCTIBLE, and OOP MAX fields: return "$0".
    - Do NOT return null for these numeric cost fields.
22. CARRIER: The carrier is the HEALTH INSURANCE COMPANY that underwrites the plan (e.g., Cigna, Aetna, UnitedHealthcare, BlueCross, Blue Shield, Anthem, Kaiser Permanente, Humana). It is NEVER the employer, company, or group that offers the plan to employees. Look for carrier names in headers, footers, or document titles. Common patterns: "UnitedHealthcare", "Cigna", "Aetna", "Anthem", "Blue Cross", "Kaiser".
23. PLAN_NAME: Extract the actual plan name, not employer group names. For UnitedHealthcare documents, look for patterns like "Choice Plus HDHP 3300", "Options PPO", etc. Do NOT return boilerplate text like "Summary of Benefits" or legal disclaimers. The plan name should be concise and descriptive of the actual insurance product.
24. PLAN_SOURCE: Extract the unique plan identifier, member ID prefix, or policy number if available from the document. If not available, return null (the pipeline will use the filename). Do NOT return "PDF" or generic values.

HDHP (High Deductible Health Plan) DETECTION:
- Look ONLY for explicit mentions of "HDHP" or "HSA" in the plan type, plan name, or headers.
- CRITICAL: DO NOT guess HDHP status based on high dollar amounts like $1,400+ deductibles. It MUST explicitly state "HDHP" or "HSA".
- Set hdhp: true only if these exact words are explicitly detected.
"""

        prompt = f"""
        Extract the Summary of Benefits and Coverage data from the following text.
        The text includes raw text and STRUCTURED TABLES. You should heavily rely on the STRUCTURED TABLES for extracting costs.
        Return the structured JSON exactly matching the requested schema.

        {FORMATTING_RULES}

        Document Text:
        {text}
        """

        print(f"  [LLM] Sending {len(text)} chars to GPT-4o for parsing...")
        
        # Retry logic for OpenAI API calls with exponential backoff
        max_retries = 3
        base_delay = 2
        
        for attempt in range(max_retries):
            try:
                completion = self.client.beta.chat.completions.parse(
                    model="gpt-4o-2024-08-06",
                    messages=[
                        {"role": "system", "content": "You are a precise data extraction expert reading SBC health insurance documents. You MUST follow the formatting rules provided by the user exactly."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format=MasterSBCSchema,
                )
                break  # Success, exit retry loop
                
            except Exception as e:
                print(f"  [LLM] Attempt {attempt + 1} failed: {str(e)}")
                
                if attempt == max_retries - 1:  # Last attempt
                    print(f"  [LLM] All {max_retries} attempts failed, raising exception")
                    raise e
                
                # Wait before retrying with exponential backoff
                delay = base_delay * (2 ** attempt)
                print(f"  [LLM] Retrying in {delay} seconds...")
                import time
                time.sleep(delay)
        
        result = completion.choices[0].message.parsed

        # Normalize plan name and pharmacy tiers using text-backed rules
        result.plan_information.plan_name = self._extract_plan_name_from_text(
            text,
            result.plan_information.plan_name,
            result.plan_information.carrier or ''
        )
        for tier_field in ['tier_1_copay', 'tier_2_copay', 'tier_3_copay', 'tier_4_copay']:
            current_value = getattr(result.pharmacy, tier_field, None)
            normalized = self._normalize_pharmacy_tier(current_value)
            setattr(result.pharmacy, tier_field, normalized)

        # Post-process office visit coinsurance: prefer explicit copay when present
        # and only keep a coinsurance % for PCP/Specialist if a percent is explicitly
        # present near the corresponding keyword in the source text. This avoids
        # pulling a generic "20%" from nearby imaging/facility rows into the
        # ──────────────────────────────────────────────────────────────────────
        # CRITICAL: Pharmacy and Medical rules moved to rules_engine.py
        
        def fix_medical_modifiers(section, copay_mod_field, coinsurance_mod_field, service_name):
            """Ensure copay_modifier and coinsurance_modifier match if needed (we'll let rules_engine handle the real logic)"""
            pass

        print(f"  [LLM] Response received")
        print(f"    Carrier: {result.plan_information.carrier}")
        print(f"    Plan: {result.plan_information.plan_name}")
        print(f"    Type: {result.plan_information.plan_type}")
        print(f"    PC Copay: {result.office_visits.primary_care_copay}")
        print(f"    ER Copay: {result.hospital_surgical.er_copay}")
        print(f"    Tier 1: {result.pharmacy.tier_1_copay}")
        
        # ──────────────────────────────────────────────────────────────────────
        # POST-PROCESSING: Inpatient Copay Per-Day Rule
        # Business rule: if raw text says "X/day" or "per day" near the inpatient
        # section, multiply the extracted copay by 3 (3-day max exposure standard)
        # ──────────────────────────────────────────────────────────────────────
        inp_copay = result.hospital_surgical.inpatient_copay
        if inp_copay:
            # Collect text around the inpatient / hospital stay context
            inpatient_section = ""
            idx = text.lower().find('inpatient')
            if idx != -1:
                inpatient_section += text[max(0, idx - 100):idx + 600]
            idx2 = text.lower().find('hospital stay')
            if idx2 != -1:
                inpatient_section += text[max(0, idx2 - 100):idx2 + 600]
            
            has_per_day = bool(re.search(
                r'(copay/day|per\s+day|/day|\b\d+\s+days?\b)',
                inpatient_section, re.IGNORECASE
            ))
            
            if has_per_day:
                dollar_match = re.search(r'\$([\d,]+)', str(inp_copay))
                if dollar_match:
                    amount = int(dollar_match.group(1).replace(',', ''))
                    new_amount = amount * 3
                    result.hospital_surgical.inpatient_copay = f"${new_amount:,}"
                    print(f"  [FIX] Inpatient Copay: Per-day detected -> ${amount} x 3 = ${new_amount:,}")
            else:
                print(f"  [OK] Inpatient Copay: No per-day charge, keeping '{inp_copay}'")

        # ──────────────────────────────────────────────────────────────────────
        # CRITICAL: Pharmacy and Medical rules moved to rules_engine.py
        
        # ──────────────────────────────────────────────────────────────────────
        # ─── POST-PROCESSING: COINSURANCE-ONLY PLANS VALIDATION ─────────────
        # ──────────────────────────────────────────────────────────────────────
        # Fix cases where document shows coinsurance but AI extracted as copays
        
        print(f"\n  [VALIDATION] Checking for coinsurance-only plan patterns...")
        
        def has_consistent_coinsurance_pattern(text):
            """Check if document consistently shows coinsurance (e.g., 10%, 20%) without copay amounts"""
            # Look for patterns like "10% coinsurance" appearing multiple times
            coinsurance_matches = re.findall(r'\b(\d+)%\s*coinsurance', text, re.IGNORECASE)
            dollar_matches = re.findall(r'\$\d+\s*(?:copay|copayment)', text, re.IGNORECASE)
            
            # If we see repeated coinsurance percentages (3+ times) but copays are much less frequent
            return len(coinsurance_matches) >= 3 and len(coinsurance_matches) > len(dollar_matches) * 2
        
        if has_consistent_coinsurance_pattern(text):
            print(f"    [VALIDATION] Detected coinsurance-only pattern - validating extractions...")
            
            # Common coinsurance percentages found in text
            coinsurance_values = re.findall(r'\b(\d+)%', text)
            most_common_coinsurance = None
            if coinsurance_values:
                from collections import Counter
                counter = Counter(coinsurance_values)
                most_common_coinsurance = f"{counter.most_common(1)[0][0]}%"
                print(f"    [VALIDATION] Most common coinsurance: {most_common_coinsurance}")
            
            # Validate office visits
            office = result.office_visits
            if office.primary_care_copay == "$0" and office.primary_care_coinsurance in [None, "0%"]:
                if most_common_coinsurance:
                    office.primary_care_coinsurance = most_common_coinsurance
                    print(f"    [FIX] Primary Care: Set coinsurance to {most_common_coinsurance}")
            
            if office.specialist_copay == "$0" and office.specialist_coinsurance in [None, "0%"]:
                if most_common_coinsurance:
                    office.specialist_coinsurance = most_common_coinsurance
                    print(f"    [FIX] Specialist: Set coinsurance to {most_common_coinsurance}")
            
            # Validate hospital services
            hospital = result.hospital_surgical
            for service_name, copay_field, coinsurance_field in [
                ("Inpatient", "inpatient_copay", "inpatient_coinsurance"),
                ("Outpatient", "op_hospital_copay", "op_hospital_coinsurance"),
                ("Emergency Room", "er_copay", "er_coinsurance")
            ]:
                copay_val = getattr(hospital, copay_field, None)
                coinsurance_val = getattr(hospital, coinsurance_field, None)
                
                if copay_val == "$0" and coinsurance_val in [None, "0%"]:
                    if most_common_coinsurance:
                        setattr(hospital, coinsurance_field, most_common_coinsurance)
                        print(f"    [FIX] {service_name}: Set coinsurance to {most_common_coinsurance}")
            
            # Validate urgent care & imaging
            imaging = result.urgent_care_labs_imaging
            for service_name, copay_field, coinsurance_field in [
                ("Urgent Care", "urgent_care_copay", "urgent_care_coinsurance"),
                ("Lab Services", "lab_services_copay", "lab_services_coinsurance"),
                ("X-Ray", "xray_copay", "xray_coinsurance"),
                ("Medical Imaging", "medical_imaging_copay", "medical_imaging_coinsurance")
            ]:
                copay_val = getattr(imaging, copay_field, None)
                coinsurance_val = getattr(imaging, coinsurance_field, None)
                
                if copay_val == "$0" and coinsurance_val in [None, "0%"]:
                    if most_common_coinsurance:
                        setattr(imaging, coinsurance_field, most_common_coinsurance)
                        print(f"    [FIX] {service_name}: Set coinsurance to {most_common_coinsurance}")
        
        # ──────────────────────────────────────────────────────────────────────
        # ─── POST-PROCESSING: DEDUCTIBLE TYPE AND STATUS FIELD POPULATION ───
        # ──────────────────────────────────────────────────────────────────────
        # Fix missing deductible_type and populate deductible_status fields
        
        print(f"\n  [POST] Setting deductible type and status fields...")
        
        # Determine deductible type based on deductible amounts
        deductibles = result.deductibles_and_coinsurance
        individual_ded = deductibles.individual_deductible or "$0"
        family_ded = deductibles.family_deductible or "$0"
        
        if "the overall family deductible must be met before the plan begins to pay" in text.lower():
            deductibles.deductible_type = "True Individual Family"
        else:
            deductibles.deductible_type = "Embedded - Traditional Style"
        
        print(f"    [DEDUCTIBLE] Type set to: {deductibles.deductible_type}")
        
        # Determine default deductible status based on plan structure
        is_no_deductible = (individual_ded == "$0")
        hdhp = result.plan_information.hdhp
        
        if is_no_deductible:
            default_status = "No"  # Deductible doesn't apply
        elif hdhp:
            default_status = "Yes"  # HDHP - deductible applies to most services
        else:
            default_status = "No"   # Traditional plan - many services waived
        
        print(f"    [STATUS] Default deductible status: {default_status}")
        
        # Populate deductible_status fields for all sections
        def set_deductible_status(section, field_pairs):
            for copay_field, coinsurance_field in field_pairs:
                # Set copay deductible status
                copay_status_field = copay_field + '_deductible_status'
                if hasattr(section, copay_status_field) and getattr(section, copay_status_field) is None:
                    modifier = getattr(section, copay_field + '_modifier', None)
                    if modifier and "Deductible Waived" in str(modifier):
                        setattr(section, copay_status_field, "No")
                    elif modifier and "After Deductible" in str(modifier):
                        setattr(section, copay_status_field, "Yes")
                    else:
                        setattr(section, copay_status_field, default_status)
                
                # Set coinsurance deductible status
                coinsurance_status_field = coinsurance_field + '_deductible_status'
                if hasattr(section, coinsurance_status_field) and getattr(section, coinsurance_status_field) is None:
                    modifier = getattr(section, coinsurance_field + '_modifier', None)
                    if modifier and "Deductible Waived" in str(modifier):
                        setattr(section, coinsurance_status_field, "No")
                    elif modifier and "After Deductible" in str(modifier):
                        setattr(section, coinsurance_status_field, "Yes")
                    else:
                        setattr(section, coinsurance_status_field, default_status)
        
        # Apply to office visits
        set_deductible_status(result.office_visits, [
            ('primary_care_copay', 'primary_care_coinsurance'),
            ('specialist_copay', 'specialist_coinsurance')
        ])
        
        # Apply to hospital surgical  
        set_deductible_status(result.hospital_surgical, [
            ('inpatient_copay', 'inpatient_coinsurance'),
            ('op_hospital_copay', 'op_hospital_coinsurance'),
            ('er_copay', 'er_coinsurance')
        ])
        
        # Apply to urgent care, labs & imaging
        set_deductible_status(result.urgent_care_labs_imaging, [
            ('urgent_care_copay', 'urgent_care_coinsurance'),
            ('lab_services_copay', 'lab_services_coinsurance'),
            ('xray_copay', 'xray_coinsurance'),
            ('medical_imaging_copay', 'medical_imaging_coinsurance')
        ])
        
        # Special handling for pharmacy deductible status
        pharmacy = result.pharmacy
        if hasattr(pharmacy, 'pharmacy_deductible_deductible_status') and pharmacy.pharmacy_deductible_deductible_status is None:
            pharmacy_ded = pharmacy.pharmacy_deductible or "$0"
            pharmacy.pharmacy_deductible_deductible_status = "Yes" if pharmacy_ded != "$0" else "No"
        
        # Pharmacy tiers deductible status
        for tier_num in range(1, 6):
            for field_type in ['copay', 'coinsurance']:
                status_field = f'tier_{tier_num}_{field_type}_deductible_status'
                if hasattr(pharmacy, status_field) and getattr(pharmacy, status_field) is None:
                    modifier_field = f'tier_{tier_num}_{field_type}_modifier'
                    modifier = getattr(pharmacy, modifier_field, None)
                    if modifier and "Deductible Waived" in str(modifier):
                        setattr(pharmacy, status_field, "No")
                    elif modifier and "After" in str(modifier):
                        setattr(pharmacy, status_field, "Yes")
                    else:
                        setattr(pharmacy, status_field, default_status)
        
        print(f"  [POST] Deductible type and status fields populated")
        
        print(f"  [POST] All post-processing validation complete")
        
        return result
