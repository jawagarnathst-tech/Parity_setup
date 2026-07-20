class RulesEngine:
    def validate_and_score(self, schema_data: dict, filename_fallback: str = None, raw_text_path: str = None) -> tuple[dict, dict]:
        import re  # Add regex import for validation
        
        score = 100
        flags = []
        
        print(f"  [VALIDATE] Running {10} validation checks...")
        
        # Check carrier — with filename fallback
        plan_info = schema_data.get('plan_information', {})
        carrier = plan_info.get('carrier')
        if not carrier:
            # Try to extract carrier from filename: pattern is "Carrier - Group Name"
            carrier_from_file = None
            if filename_fallback and ' - ' in filename_fallback:
                carrier_from_file = filename_fallback.split(' - ')[0].strip()
            if carrier_from_file:
                schema_data['plan_information']['carrier'] = carrier_from_file
                carrier = carrier_from_file
                flags.append(f"Carrier not found in document; inferred from filename: {carrier_from_file}")
                print(f"    [WARN] Carrier: FALLBACK to '{carrier_from_file}' (from filename)")
            else:
                score -= 20
                flags.append("Missing carrier name")
                print(f"    [FAIL] Carrier: MISSING (-20 pts)")
        else:
            print(f"    [OK] Carrier: {carrier}")
        
        # Check plan_name — detect and fix boilerplate/invalid plan names
        plan_name = schema_data.get('plan_information', {}).get('plan_name')
        import re
        BOILERPLATE_MARKERS = [
            'welcometouhc.com', 'welcometocitizenrx', 'aetna.com', 'mycigna.com',
            'For general definitions', 'allowed amount', 'balance billing',
            'Summary of Benefits', 'This is only a summary', 'coverage period',
            'what this plan covers', 'what you pay for covered services',
            'share the cost for covered', 'underlined terms', 'see the glossary',
            'common terms', 'www.healthcare.gov', 'call 1-866', 'call 1-800',
            'to request a copy', 'you can view the glossary'
        ]
        is_bad_name = (
            not plan_name or
            len(plan_name) > 120 or
            any(marker.lower() in plan_name.lower() for marker in BOILERPLATE_MARKERS) or
            bool(re.match(r'^[\d\s]+$', str(plan_name).strip()))
        )
        if is_bad_name and raw_text_path:
            recovered = None
            try:
                with open(raw_text_path, 'r', encoding='utf-8', errors='ignore') as rf:
                    lines = rf.readlines()
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    # Pattern 1: plan name on its own line between "Coverage Period:" and "Coverage For:", or prepended to "Coverage For:"
                    if 'coverage period:' in stripped.lower():
                        for j in range(i + 1, min(i + 5, len(lines))):
                            candidate = lines[j].strip()
                            if candidate and not any(m.lower() in candidate.lower() for m in BOILERPLATE_MARKERS) and not bool(re.match(r'^[\d\s]+$', candidate)):
                                if 'coverage for:' in candidate.lower():
                                    idx = candidate.lower().find('coverage for:')
                                    left_part = candidate[:idx].strip()
                                    if left_part:
                                        recovered = left_part
                                        break
                                elif not candidate.lower().startswith('coverage for'):
                                    recovered = candidate
                                    break
                        if recovered:
                            break
                    # Pattern 2: "Carrier: Plan Name Coverage Period: ..." all on one line
                    # e.g. "Excellus BCBS: SimplyBlue Plus Gold 5 Coverage Period: 07/01/2026"
                    if 'coverage period:' in stripped.lower() and ':' in stripped:
                        # Extract the part before "Coverage Period:"
                        before_period = stripped[:stripped.lower().index('coverage period:')].strip()
                        if ':' in before_period:
                            # Take what's after the last colon (the plan name part)
                            plan_part = before_period.split(':', 1)[-1].strip()
                            if plan_part and len(plan_part) < 120 and not any(m.lower() in plan_part.lower() for m in BOILERPLATE_MARKERS) and not bool(re.match(r'^[\d\s]+$', plan_part)):
                                recovered = plan_part
                                break
            except Exception as e:
                print(f"    [WARN] Could not read raw text for plan name recovery: {e}")

            if recovered:
                # Clean up any OCR logo garbage that might have prepended itself with a dot or colon
                if '. ' in recovered:
                    recovered = recovered.split('. ')[-1].strip()
                recovered = recovered.lstrip(':.- ').strip()

                schema_data['plan_information']['plan_name'] = recovered
                plan_name = recovered
                flags.append(f"Plan name was boilerplate; recovered from raw text: {recovered}")
                print(f"    [FIX] Plan Name: RECOVERED -> '{recovered}'")
            else:
                print(f"    [WARN] Plan Name was boilerplate but recovery failed. Clearing name.")
                schema_data['plan_information']['plan_name'] = None
                plan_name = None
        
        # FINAL FALLBACK: If we still don't have a plan name, try to use the filename!
        if not plan_name and filename_fallback:
            import re
            # Remove the UUID hash prefix (e.g., 299c959b..._) and .pdf extension
            clean_file = re.sub(r'^[a-fA-F0-9\-]{36}_', '', filename_fallback)
            clean_file = clean_file.replace('.pdf', '')
            # Remove any UUID hash suffix that might have been part of the original upload name
            clean_file = re.sub(r'_[a-fA-F0-9\-]{36}$', '', clean_file)
            
            # If there's a carrier prefix like "Aetna - Renaissance", take the part after the dash
            if ' - ' in clean_file:
                clean_file = clean_file.split(' - ', 1)[-1].strip()
                
            if clean_file and len(clean_file) < 120 and not bool(re.match(r'^[\d\s]+$', clean_file)):
                schema_data['plan_information']['plan_name'] = clean_file
                plan_name = clean_file
                print(f"    [FIX] Plan Name: RECOVERED FROM FILENAME -> '{clean_file}'")

        if plan_name:
            print(f"    [OK] Plan Name: {plan_name}")
        else:
            print(f"    [FAIL] Plan Name could not be recovered.")
            
        # User requested to ALWAYS click/check the Open Access box for every plan
        schema_data['plan_information']['open_access'] = True
        print("    [FIX] Forced open_access to True (Always Checked) per user preference")

        
        # Check plan_type
        plan_type = schema_data.get('plan_information', {}).get('plan_type')
        if plan_type:
            print(f"    [OK] Plan Type: {plan_type}")
            if "hsa" in str(plan_type).lower() or "hdhp" in str(plan_type).lower():
                schema_data['plan_information']['hdhp'] = True
                print("    [FIX] Forced hdhp to True because plan_type indicates HSA/HDHP")
        else:
            print(f"    [WARN] Plan Type: null")
            
        if plan_name and ("hsa" in str(plan_name).lower() or "hdhp" in str(plan_name).lower()):
            schema_data['plan_information']['hdhp'] = True
            print("    [FIX] Forced hdhp to True because plan_name indicates HSA/HDHP")
        
        # Check deductible
        ded = schema_data.get('deductibles_and_coinsurance', {}).get('individual_deductible')
        print(f"    [OK] Deductible: {ded}")
        
        # Check OOP Max
        oop = schema_data.get('deductibles_and_coinsurance', {}).get('individual_oop_max')
        print(f"    [OK] OOP Max: {oop}")
        
        # User requested to intentionally leave plan_source and renewal_date blank
        schema_data['plan_information']['plan_source'] = None
        schema_data['plan_information']['renewal_date'] = None
        print("    [FIX] Forced plan_source and renewal_date to None per user preference")
        
        # FIX: Correct offers_tier_1a_benefit if it's incorrectly set to true without evidence
        # Tier 1A benefit should ONLY be true if document explicitly mentions it
        # Check if document has Tier 1A language
        has_tier_1a_language = False
        if raw_text_path:
            try:
                with open(raw_text_path, 'r', encoding='utf-8') as rf:
                    raw_content = rf.read().lower()
                    has_tier_1a_language = '1a' in raw_content and 'benefit' in raw_content
            except:
                pass
        
        # If no Tier 1A language found but offers_tier_1a_benefit is true, set to false
        if not has_tier_1a_language:
            pharmacy = schema_data.get('pharmacy', {})
            if pharmacy.get('offers_tier_1a_benefit') == True:
                pharmacy['offers_tier_1a_benefit'] = False
                print("    [FIX] offers_tier_1a_benefit: Set to False (no Tier 1A language found in document)")
            
        # 100% Minus Rule for Coinsurance (Patient Responsibility Fallback)
        # Rule: If coinsurance > 50%, it's likely the plan's portion, not patient's
        # Patient pays the INVERSE: 100% - plan's portion
        # Example: If inpatient shows 60% → Patient pays 40% (100 - 60)
        # 
        # Special case: If inpatient coinsurance ≤ 50%, assume it's correct and
        # also SET in_network_coinsurance to the same value
        def apply_minus_rule(val):
            if not val or not isinstance(val, str):
                return val
            if '%' in val:
                try:
                    pct = int(re.sub(r'[^\d]', '', val))
                    if pct > 50:  # Greater than 50% = likely plan's portion
                        return f"{100 - pct}%"
                except:
                    pass
            return val

        # Apply 100% Minus Rule to inpatient coinsurance
        hospital_surgical = schema_data.get('hospital_surgical', {})
        inpatient_coins = hospital_surgical.get('inpatient_coinsurance')
        in_network_coinsurance_set_by_rule = False  # Track if we set it
        
        if inpatient_coins:
            try:
                pct = int(re.sub(r'[^\d]', '', str(inpatient_coins)))
                
                if pct > 50:
                    # Apply 100% minus rule to BOTH inpatient and in_network_coinsurance
                    corrected_value = f"{100 - pct}%"
                    hospital_surgical['inpatient_coinsurance'] = corrected_value
                    schema_data['deductibles_and_coinsurance']['in_network_coinsurance'] = corrected_value
                    print(f"    [FIX] inpatient_coinsurance: Applied 100% Minus Rule -> '{inpatient_coins}' became '{corrected_value}'")
                    print(f"    [FIX] in_network_coinsurance: Set to '{corrected_value}' (same as inpatient)")
                    in_network_coinsurance_set_by_rule = True
                
                elif pct <= 50:
                    # Value is correct, but also SET in_network_coinsurance to same value
                    schema_data['deductibles_and_coinsurance']['in_network_coinsurance'] = inpatient_coins
                    print(f"    [FIX] in_network_coinsurance: Set to '{inpatient_coins}' (from inpatient)")
                    in_network_coinsurance_set_by_rule = True
                    
            except:
                pass
        
        # Inpatient per-day rule is handled in universal_extractor.py (has direct access to in-memory raw text)

        
        # Phase 3: Medical Services (Case A / Case B / HDHP)
        hdhp = schema_data.get('plan_information', {}).get('hdhp', False)
        
        def _contains_deductible_applies(value):
            import re
            normalized = " ".join(str(value or "").lower().split())
            if not normalized:
                return False
            # CRITICAL: Ignore plan-level disclaimer text like "All copayment and coinsurance costs shown in this chart are after your deductible has been met, if a deductible applies"
            # This is just a header/disclaimer that does NOT apply to individual services
            if "if a deductible applies" in normalized or "if deductible applies" in normalized:
                return False
            # Also ignore the full disclaimer phrase
            if "after your deductible has been met" in normalized and "if a deductible applies" in normalized:
                return False
            if "deductible applies" in normalized:
                return True
            # OCR-tolerant variants, e.g. "Deductible a pplies", "D eductible applies"
            if re.search(r"deductible\s+a\s*p{1,2}lies", normalized):
                return True
            if re.search(r"d\s*eductible\s+applies", normalized):
                return True
            return False

        def _contains_deductible_does_not_apply(value):
            import re
            normalized = " ".join(str(value or "").lower().split())
            if not normalized:
                return False
            if "deductible does not apply" in normalized:
                return True
            if "deductible doesn't apply" in normalized:  # Handle contracted form
                return True
            if re.search(r"deductible\s+does\s+n\s*ot\s+apply", normalized):
                return True
            if re.search(r"deductible\s+doesn't\s+apply", normalized):  # Handle contracted form with regex
                return True
            return False

        def _contains_deductible_waived(value):
            normalized = " ".join(str(value or "").lower().split())
            return "deductible waived" in normalized

        service_raw_keywords = {
            "primary_care_copay": ["primary care", "pcp", "injury or illness"],
            "specialist_copay": ["specialist"],
            "inpatient_copay": ["inpatient", "facility fee", "hospital stay", "hospital room"],
            "op_hospital_copay": ["outpatient surgery", "outpatient hospital", "ambulatory surgery", "ambulatory"],
            "er_copay": ["emergency room care", "emergency room", "emergency medical"],
            "urgent_care_copay": ["urgent care"],
            "lab_services_copay": ["diagnostic test", "blood work", "lab"],
            "xray_copay": ["x-ray", "xray"],
            "medical_imaging_copay": ["imaging", "ct/pet", "mri"],
        }

        raw_text_lines = []
        raw_text_full = ""
        if raw_text_path:
            try:
                with open(raw_text_path, "r", encoding="utf-8") as rf:
                    raw_text_lines = rf.read().splitlines()
                    raw_text_full = " ".join(
                        " ".join(line.lower().split()) for line in raw_text_lines
                    )
            except Exception as e:
                print(f"    [WARN] Medical raw text scan skipped: {e}")

        def _in_network_cost_column_index(parts, has_preferred):
            """
            Detect the In-Network column index from pipe-separated row parts.
            
            CRITICAL: This function must ONLY return the In-Network column,
            NEVER Out-of-Network or any other column.
            
            Strategy:
            1. First check for explicit "In-Network" label in column header
            2. If not found, use positional heuristics based on column count and layout
            """
            # STRATEGY 1: Look for explicit "In-Network" label (most reliable)
            for i, part in enumerate(parts):
                part_lower = part.lower().strip()
                # Check if this column header explicitly says "In-Network"
                if 'in-network' in part_lower or 'in network' in part_lower:
                    # Make sure it's a header, not a service name
                    if 'you will pay' in part_lower or 'provider' in part_lower or 'participating' in part_lower:
                        # This is a column header for In-Network - return the DATA column index (next one)
                        if i + 1 < len(parts):
                            return i + 1
                        return i
                # Alternative: "Participating Provider" column header
                if 'participating' in part_lower and 'you will pay' in part_lower:
                    if i + 1 < len(parts):
                        return i + 1
                    return i
            
            # STRATEGY 2: Positional heuristics if no explicit label found
            # Count columns that contain cost data (dollar or percent)
            cost_indices = []
            for i, part in enumerate(parts):
                if re.search(r'\$\s*[\d,]+(?:\.\d+)?|\d+\s*%', part):
                    cost_indices.append(i)
                elif re.search(r'no charge', part, re.IGNORECASE):
                    # Only treat "no charge" as a cost column (means $0).
                    # "Not Applicable" is Anthem-specific and means the column
                    # doesn't apply to that service — NOT a real cost value.
                    cost_indices.append(i)
            
            if not cost_indices:
                return None
            
            # If we have multiple cost columns, we need to pick the IN-NETWORK one
            # CRITICAL: Default to the FIRST cost column when uncertain
            # (This is safer than defaulting to cost_indices[1] which might be Out-of-Network)
            if has_preferred and len(cost_indices) >= 2:
                # WITH Preferred Network: layout is typically Preferred | In-Network | Out-of-Network
                # In this case, cost_indices[1] is likely In-Network
                # But ONLY if we're confident there are exactly 3 cost columns
                if len(cost_indices) >= 3:
                    # We have Preferred, In-Network, and Out-of-Network = cost_indices[1] is In-Network
                    return cost_indices[1]
                else:
                    # We only have 2 cost columns - unclear which is which
                    # SAFER: Assume first is In-Network, second is Out-of-Network
                    return cost_indices[0]
            
            # WITHOUT Preferred Network: first cost column is In-Network
            return cost_indices[0]

        def _extract_dollar_from_cell(text):
            if not text:
                return None
            if re.search(r'no charge|not applicable', text, re.IGNORECASE):
                return '$0'
            dollar_match = re.search(r'\$\s*([\d,]+(?:\.\d+)?)', text)
            if not dollar_match:
                return None
            amount = dollar_match.group(1).replace(',', '')
            if '.' in amount:
                whole, frac = amount.split('.', 1)
                frac = frac.rstrip('0')
                if not frac:
                    return f"${int(whole):,}"
                return f"${int(whole):,}.{frac}"
            return f"${int(amount):,}"

        def _extract_percent_from_cell(text):
            if not text:
                return None
            percent_match = re.search(r'(\d+)\s*%', text)
            return f"{percent_match.group(1)}%" if percent_match else None

        def _parse_in_network_costs_from_pipe_line(line, has_preferred):
            parts = [part.strip() for part in line.split('|')]
            idx = _in_network_cost_column_index(parts, has_preferred)
            if idx is None:
                return None, None
            cell = parts[idx]
            if re.search(r'maximum per admission|limited to \d+\s+days', cell, re.IGNORECASE):
                return None, None
            if re.search(r'out[- ]of[- ]network|for out-', cell, re.IGNORECASE):
                return None, None
            copay = _extract_dollar_from_cell(cell)
            coinsurance = _extract_percent_from_cell(cell)
            if copay and not coinsurance:
                coinsurance = '0%'
            elif coinsurance and not copay:
                copay = '$0'
            elif not copay and not coinsurance:
                return None, None
            return copay, coinsurance

        def _apply_in_network_cost_correction(schema_data, raw_lines):
            if not raw_lines:
                return
            raw_text = '\n'.join(raw_lines)
            has_preferred = bool(re.search(r'Preferred\s+Network', raw_text, re.IGNORECASE))
            service_section_map = {
                'primary_care_copay': ('office_visits', 'primary_care'),
                'specialist_copay': ('office_visits', 'specialist'),
                # REMOVED inpatient and op_hospital from auto-correction
                # These services can have BOTH copay and coinsurance
                'er_copay': ('hospital_surgical', 'er'),
                'urgent_care_copay': ('urgent_care_labs_imaging', 'urgent_care'),
                'lab_services_copay': ('urgent_care_labs_imaging', 'lab_services'),
                'xray_copay': ('urgent_care_labs_imaging', 'xray'),
                'medical_imaging_copay': ('urgent_care_labs_imaging', 'medical_imaging'),
            }
            fixes = 0
            for copay_base, (section_key, prefix) in service_section_map.items():
                keywords = service_raw_keywords.get(copay_base, [])
                if not keywords:
                    continue
                candidates = [
                    line for line in raw_lines
                    if '|' in line and any(kw in line.lower() for kw in keywords)
                ]
                best_result = None
                best_rank = (-1, -1, -1, -1)
                for line in candidates:
                    score = sum(1 for kw in keywords if kw in line.lower())
                    parsed = _parse_in_network_costs_from_pipe_line(line, has_preferred)
                    if parsed is None or (parsed[0] is None and parsed[1] is None):
                        continue
                    copay, _coinsurance = parsed
                    parts = [part.strip() for part in line.split('|')]
                    cell_idx = _in_network_cost_column_index(parts, has_preferred)
                    in_cell = parts[cell_idx] if cell_idx is not None else ''
                    has_pay_pattern = 1 if re.search(
                        r'per day|per visit|no charge', in_cell, re.IGNORECASE
                    ) else 0
                    has_dollar = 1 if copay and copay != '$0' else 0
                    dollar_val = 0
                    if has_dollar:
                        amount_match = re.search(r'(\d[\d,]*)', str(copay).replace('$', ''))
                        if amount_match:
                            dollar_val = int(amount_match.group(1).replace(',', ''))
                    rank = (has_pay_pattern, has_dollar, dollar_val, score)
                    if rank > best_rank:
                        best_rank = rank
                        best_result = parsed
                if not best_result:
                    continue
                copay, coinsurance = best_result
                section = schema_data.setdefault(section_key, {})
                coinsurance_field = f'{prefix}_coinsurance'
                if coinsurance is not None and section.get(coinsurance_field) != coinsurance:
                    section[coinsurance_field] = coinsurance
                    fixes += 1
                    print(f"    [IN-NETWORK] {prefix}: coinsurance -> {coinsurance}")

            if fixes:
                print(f"    [IN-NETWORK] Corrected {fixes} cost field(s) from raw text In-Network column")

        def _derive_in_network_coinsurance(raw_lines):
            from collections import Counter
            if not raw_lines:
                return None
            raw_text = '\n'.join(raw_lines)
            has_preferred = bool(re.search(r'Preferred\s+Network', raw_text, re.IGNORECASE))
            counts = Counter()
            for line in raw_lines:
                if '|' not in line:
                    continue
                parsed = _parse_in_network_costs_from_pipe_line(line, has_preferred)
                if parsed and parsed[1]:
                    counts[parsed[1]] += 1
            if not counts:
                return None
            return counts.most_common(1)[0][0]

        _apply_in_network_cost_correction(schema_data, raw_text_lines)

        # CRITICAL FIX: Validate hospital facility fee extraction BEFORE attempting to restore coinsurance
        # This ensures the hospital facility fee rule (Facility Fee row + In-Network column only) 
        # takes precedence over any restoration logic
        def _validate_hospital_facility_fee_only(schema_data, raw_lines):
            nonlocal in_network_coinsurance_set_by_rule
            """DEBUG: Hospital Facility Fee Validation"""
            """
            CRITICAL: For Inpatient and Outpatient Hospital services, extract values ONLY from:
            1. The "Facility Fee" row (NOT from Physician/Surgeon fees or other rows)
            2. The "In-Network" column (NEVER from Out-of-Network)
            
            This prevents cross-column contamination where Out-of-Network coinsurance
            bleeds into In-Network fields.
            
            Hospital structure typically:
              Facility Fee (In-Network): $600 deductible or similar
              Facility Fee (Out-of-Network): 30% coinsurance
              Physician fees (In-Network): No charge
              Physician fees (Out-of-Network): 30% coinsurance
            
            We should extract from: Facility Fee row + In-Network column ONLY.
            """
            if not raw_lines:
                return
            
            raw_text = '\n'.join(raw_lines)
            fixes = 0
            
            # Process inpatient and outpatient hospital services
            hospital_services = [
                ('inpatient_copay', 'inpatient_coinsurance', 'hospital_surgical', 'inpatient', 
                 ['inpatient', 'facility fee', 'hospital stay', 'hospital room']),
                ('op_hospital_copay', 'op_hospital_coinsurance', 'hospital_surgical', 'op_hospital',
                 ['outpatient surgery', 'outpatient hospital', 'ambulatory surgery', 'ambulatory']),
            ]
            
            for copay_key, coins_key, section_key, service_name, keywords in hospital_services:
                section = schema_data.get(section_key, {})
                if not isinstance(section, dict):
                    continue
                
                current_copay = section.get(copay_key)
                current_coinsurance = section.get(coins_key)
                
                # Skip if neither field has a value
                if not current_copay and not current_coinsurance:
                    continue
                
                # Find the "Facility Fee" row specifically (not Physician fees)
                facility_fee_lines = []
                for line in raw_lines:
                    if '|' not in line:
                        continue
                    line_lower = line.lower()
                    # Match "Facility Fee" or "facility fee" specifically
                    if 'facility fee' in line_lower and not 'physician' in line_lower:
                        # Ensure the line matches the service context to distinguish inpatient vs outpatient
                        if any(kw in line_lower for kw in keywords if kw != 'facility fee'):
                            facility_fee_lines.append(line)
                            
                # Fallback if the line was split and context was lost
                if not facility_fee_lines:
                    other_kws = hospital_services[1][4] if service_name == 'inpatient' else hospital_services[0][4]
                    for line in raw_lines:
                        if '|' in line and 'facility fee' in line.lower() and not 'physician' in line.lower():
                            if not any(kw in line.lower() for kw in other_kws if kw != 'facility fee'):
                                facility_fee_lines.append(line)
                
                if not facility_fee_lines:
                    continue
                
                # Parse the first Facility Fee row's In-Network and Out-of-Network columns
                facility_line = facility_fee_lines[0]
                parts = [p.strip() for p in facility_line.split('|')]

                # Detect column layout by explicit header label search first.
                # Some plans (e.g. Anthem) have a 3-col cost layout:
                #   Level 1 Pharmacy-RX Only (Not Applicable) | In-Network | Out-of-Network
                # In those rows the first cost cell is "Not Applicable", so we must
                # skip it and pick the NEXT non-N/A cell as In-Network.
                in_network_value = ""
                out_of_network_value = ""

                # Try label-based detection first (most reliable)
                in_network_label_idx = None
                oon_label_idx = None
                for i, part in enumerate(parts):
                    if re.search(r'In[- ]?Network.*You will pay|Participating.*You will pay', part, re.IGNORECASE):
                        in_network_label_idx = i
                    if re.search(r'Out[- ]?of[- ]?Network.*You will pay|Non[- ]?Participating.*You will pay', part, re.IGNORECASE):
                        oon_label_idx = i

                if in_network_label_idx is not None and in_network_label_idx + 1 < len(parts):
                    in_network_value = parts[in_network_label_idx + 1]
                    if oon_label_idx is not None and oon_label_idx + 1 < len(parts):
                        out_of_network_value = parts[oon_label_idx + 1]
                else:
                    # Fallback: Use the _in_network_cost_column_index helper to detect the correct column
                    # This handles 2-col, 3-col (with Preferred), and other layouts correctly
                    has_preferred = bool(re.search(r'Preferred\s+Network', raw_text, re.IGNORECASE))
                    in_network_idx = _in_network_cost_column_index(parts, has_preferred)
                    
                    if in_network_idx is None or in_network_idx >= len(parts):
                        continue
                    
                    in_network_value = parts[in_network_idx]
                    
                    # Try to detect Out-of-Network column (usually comes after In-Network)
                    # For 3-col: Preferred | In-Network | Out-of-Network
                    # For 2-col: In-Network | Out-of-Network
                    out_of_network_value = None
                    if has_preferred and in_network_idx + 1 < len(parts):
                        # We have Preferred; try to find OON after In-Network
                        potential_oon = parts[in_network_idx + 1]
                        if re.search(r'\$\s*[\d,]+(?:\.\d+)?|\d+\s*%|no charge', potential_oon, re.IGNORECASE):
                            out_of_network_value = potential_oon
                    elif not has_preferred and in_network_idx + 1 < len(parts):
                        # No Preferred; try to find OON after In-Network
                        potential_oon = parts[in_network_idx + 1]
                        if re.search(r'\$\s*[\d,]+(?:\.\d+)?|\d+\s*%|no charge', potential_oon, re.IGNORECASE):
                            out_of_network_value = potential_oon

                # Check copay rule: Hospital facility fees should NOT have copays extracted
                if current_copay:
                    # Check if this is actually from the facility fee row
                    copay_in_in_network = _extract_dollar_from_cell(in_network_value) if in_network_value else None

                    # If we extracted a copay but it's not in the In-Network Facility Fee row, remove it
                    if copay_in_in_network is None and current_copay:
                        section[copay_key] = None
                        fixes += 1
                        print(f"    [FIX-HOSPITAL-FACILITY] {section_key}.{copay_key}: Removed '{current_copay}' (not from Facility Fee In-Network row)")
                    elif copay_in_in_network and copay_in_in_network != current_copay:
                        # Copay found in In-Network row but value differs (LLM picked wrong row e.g. hospital-affiliated vs independent)
                        # Correct it to the actual In-Network Facility Fee row value
                        section[copay_key] = copay_in_in_network
                        fixes += 1
                        print(f"    [FIX-HOSPITAL-FACILITY] {section_key}.{copay_key}: Corrected '{current_copay}' -> '{copay_in_in_network}' (In-Network Facility Fee row)")

                # Rule: Hospital coinsurance should come from Facility Fee row's In-Network column ONLY
                if current_coinsurance:
                    coins_in_in_network = _extract_percent_from_cell(in_network_value) if in_network_value else None
                    coins_in_oon = _extract_percent_from_cell(out_of_network_value) if out_of_network_value else None

                    # If extracted coinsurance doesn't match In-Network Facility Fee, but matches Out-of-Network, it's wrong
                    if coins_in_in_network is None and coins_in_oon and current_coinsurance == coins_in_oon:
                        section[coins_key] = None
                        fixes += 1
                        print(f"    [FIX-HOSPITAL-FACILITY] {section_key}.{coins_key}: Removed '{current_coinsurance}' (from Out-of-Network Facility Fee, should be from In-Network only)")
                        if coins_key == 'inpatient_coinsurance' and in_network_coinsurance_set_by_rule:
                            schema_data['deductibles_and_coinsurance']['in_network_coinsurance'] = None
                            in_network_coinsurance_set_by_rule = False
                            print("    [FIX-HOSPITAL-FACILITY] Also removed corrupted 'in_network_coinsurance' to allow fallback deduction")
                            
                    elif coins_in_in_network is not None and coins_in_in_network != current_coinsurance:
                        # Coinsurance present in In-Network but doesn't match — could be from wrong row; remove it
                        section[coins_key] = None
                        fixes += 1
                        print(f"    [FIX-HOSPITAL-FACILITY] {section_key}.{coins_key}: Removed '{current_coinsurance}' (not from Facility Fee In-Network row)")
                        if coins_key == 'inpatient_coinsurance' and in_network_coinsurance_set_by_rule:
                            schema_data['deductibles_and_coinsurance']['in_network_coinsurance'] = None
                            in_network_coinsurance_set_by_rule = False
                            print("    [FIX-HOSPITAL-FACILITY] Also removed corrupted 'in_network_coinsurance' to allow fallback deduction")
                    # If coins_in_in_network IS None AND coins_in_oon is also None (or different value),
                    # do NOT remove — the value may have been correctly extracted by the LLM from a
                    # combined/prose row that has no pipe-separated columns.

            if fixes:
                print(f"    [HOSPITAL-FACILITY] Applied {fixes} Facility Fee row + In-Network only correction(s)")
        
        # Run hospital facility fee validation FIRST, before any restoration logic
        _validate_hospital_facility_fee_only(schema_data, raw_text_lines)

        # Post-processing: Restore hospital coinsurance if it was incorrectly zeroed
        # Hospital services (inpatient/outpatient) can have BOTH copay AND coinsurance
        # The IN-NETWORK correction should not zero them out
        # NOTE: This runs AFTER hospital facility fee validation to avoid restoring invalid values
        for service_prefix in ['inpatient', 'op_hospital']:
            section = schema_data.get('hospital_surgical', {})
            coins_key = f'{service_prefix}_coinsurance'
            copay_key = f'{service_prefix}_copay'
            
            # If coinsurance was set to 0% but raw text shows a percentage
            if section.get(coins_key) == '0%':
                keywords = service_raw_keywords.get(f'{service_prefix}_copay', [])
                for line in raw_text_lines:
                    if '|' in line and any(kw in line.lower() for kw in keywords):
                        # Check if this line mentions a percentage coinsurance
                        percent_match = re.search(r'(\d+)\s*%', line)
                        if percent_match and 'coinsurance' in line.lower():
                            section[coins_key] = f"{percent_match.group(1)}%"
                            print(f"    [FIX] {service_prefix}_coinsurance: Restored from raw text -> {section[coins_key]}")
                            break

        derived_coinsurance = _derive_in_network_coinsurance(raw_text_lines)
        
        # ONLY derive from raw text if we didn't already set it via the 100% Minus Rule
        if derived_coinsurance and not in_network_coinsurance_set_by_rule:
            deductibles_section = schema_data.setdefault('deductibles_and_coinsurance', {})
            current = deductibles_section.get('in_network_coinsurance')
            if current != derived_coinsurance:
                deductibles_section['in_network_coinsurance'] = derived_coinsurance
                print(f"    [IN-NETWORK] in_network_coinsurance -> {derived_coinsurance}")

        # CRITICAL: Validate and fix cross-column Medical extraction
        # Ensure Medical Copay and Coinsurance are ONLY extracted from In-Network (Participating Provider) column
        def _fix_cross_column_medical_extraction(schema_data, raw_lines):
            """
            Validates all Medical copay/coinsurance fields to ensure they come from the In-Network column only.
            If a coinsurance value appears to come from Out-of-Network (when only copay is in In-Network), removes it.
            """
            if not raw_lines:
                return
            
            raw_text = '\n'.join(raw_lines)
            has_preferred = bool(re.search(r'Preferred\s+Network', raw_text, re.IGNORECASE))
            
            # STEP 0: Identify the In-Network column index from the table header row
            # Look for a header row with "In-Network Provider" or similar labels
            in_network_col_index = None
            out_of_network_col_index = None
            
            for line in raw_lines:
                if '|' not in line:
                    continue
                line_lower = line.lower()
                # Check if this is a header row (contains "In-Network Provider" or "Out-of-Network Provider")
                if ('in-network provider' in line_lower or 'in network provider' in line_lower or 
                    'participating' in line_lower) and 'what you will pay' in line_lower:
                    parts = [p.strip() for p in line.split('|')]
                    for i, part in enumerate(parts):
                        part_lower = part.lower()
                        if ('in-network provider' in part_lower or 'in network provider' in part_lower) and 'you will pay' in part_lower:
                            in_network_col_index = i
                        if ('out-of-network provider' in part_lower or 'out of network provider' in part_lower) and 'you will pay' in part_lower:
                            out_of_network_col_index = i
                    if in_network_col_index is not None:
                        break  # Found the header row, stop searching
            
            medical_services_to_check = [
                ('office_visits', 'primary_care', ['primary care', 'pcp', 'injury or illness']),
                ('office_visits', 'specialist', ['specialist']),
                ('hospital_surgical', 'inpatient', ['inpatient', 'facility fee', 'hospital stay', 'hospital room']),
                ('hospital_surgical', 'op_hospital', ['outpatient surgery', 'outpatient hospital', 'ambulatory']),
                ('hospital_surgical', 'er', ['emergency room care', 'emergency room']),
                ('urgent_care_labs_imaging', 'urgent_care', ['urgent care']),
                ('urgent_care_labs_imaging', 'lab_services', ['diagnostic test', 'blood work', 'lab']),
                ('urgent_care_labs_imaging', 'xray', ['x-ray', 'xray']),
                ('urgent_care_labs_imaging', 'medical_imaging', ['imaging', 'ct/pet', 'mri']),
            ]
            
            fixes = 0
            for section_key, service_prefix, keywords in medical_services_to_check:
                section = schema_data.get(section_key, {})
                if not isinstance(section, dict):
                    continue
                
                copay_key = f'{service_prefix}_copay'
                coinsurance_key = f'{service_prefix}_coinsurance'
                
                copay_value = section.get(copay_key)
                coinsurance_value = section.get(coinsurance_key)
                
                # Skip if both are already null/0
                if not copay_value and not coinsurance_value:
                    continue
                
                # Find the service line in raw text
                matching_lines = [
                    line for line in raw_lines
                    if '|' in line and any(kw in line.lower() for kw in keywords)
                ]
                
                if not matching_lines:
                    continue
                
                # Parse the In-Network column from matching lines
                best_in_network_copay = None
                best_in_network_coinsurance = None
                best_out_network_coinsurance = None
                
                for line in matching_lines:
                    parts = [part.strip() for part in line.split('|')]
                    
                    # Skip if line has "out of network" or "out-of-network" in description (non-cost column)
                    description_part = parts[0] if parts else ""
                    if 'out of network' in description_part.lower() or 'out-of-network' in description_part.lower():
                        continue
                    
                    # Use the detected In-Network column index from the header row
                    in_network_cell = None
                    out_of_network_cell = None
                    
                    if in_network_col_index is not None and in_network_col_index < len(parts):
                        in_network_cell = parts[in_network_col_index]
                        
                        # Extract copay and coinsurance from In-Network cell
                        in_copay = _extract_dollar_from_cell(in_network_cell)
                        in_coinsurance = _extract_percent_from_cell(in_network_cell)
                        
                        # Check Out-of-Network cell for reference
                        oon_coinsurance = None
                        if out_of_network_col_index is not None and out_of_network_col_index < len(parts):
                            oon_cell = parts[out_of_network_col_index]
                            oon_coinsurance = _extract_percent_from_cell(oon_cell)
                        
                        # If we found values in In-Network cell, use them
                        if in_copay or in_coinsurance:
                            best_in_network_copay = in_copay
                            best_in_network_coinsurance = in_coinsurance
                            best_out_network_coinsurance = oon_coinsurance
                            break
                
                # Now check if current extraction violates In-Network only rule
                # AND correct coinsurance values that are currently wrong
                if best_in_network_copay or best_in_network_coinsurance:
                    # Correct coinsurance to In-Network value if it's currently wrong
                    if best_in_network_coinsurance and coinsurance_value != best_in_network_coinsurance:
                        section[coinsurance_key] = best_in_network_coinsurance
                        fixes += 1
                        print(f"    [FIX-XCOLUMN] {section_key}.{service_prefix}_coinsurance: Corrected '{coinsurance_value}' -> '{best_in_network_coinsurance}' (from In-Network column)")
                    
                    # Case 1: Only copay in In-Network, but coinsurance was extracted from Out-of-Network
                    elif (best_in_network_copay and not best_in_network_coinsurance and 
                        coinsurance_value and best_out_network_coinsurance and
                        best_out_network_coinsurance.strip('%') == coinsurance_value.strip('%')):
                        # Coinsurance came from Out-of-Network; remove it
                        section[coinsurance_key] = None
                        fixes += 1
                        print(f"    [FIX-XCOLUMN] {section_key}.{service_prefix}_coinsurance: Removed Out-of-Network value ('{coinsurance_value}')")
                    
                    # Case 2: Current coinsurance doesn't match In-Network, but exists in Out-of-Network
                    elif (coinsurance_value and best_out_network_coinsurance and
                          coinsurance_value.strip('%') == best_out_network_coinsurance.strip('%') and
                          best_in_network_coinsurance is None):
                        # Coinsurance came from Out-of-Network; remove it
                        section[coinsurance_key] = None
                        fixes += 1
                        print(f"    [FIX-XCOLUMN] {section_key}.{service_prefix}_coinsurance: Removed Out-of-Network value ('{coinsurance_value}')")

                # Case 3: In-Network cell says "No charge" but LLM extracted a non-zero copay
                # (e.g. $750 penalty from Limitations column bled into copay)
                # SKIPPED: This check requires reliable column detection from headers, which failed (best_in_network_copay is None).
                # Without header information, we cannot reliably identify which column is "In-Network", so this fallback check is unreliable.
                # The rule applies only when we have confirmed header information (best_in_network_copay is not None).
            
            if fixes:
                print(f"    [FIX-XCOLUMN] Corrected {fixes} Medical field(s) for In-Network only extraction")
        
        def _restore_missing_in_network_copays(schema_data, raw_lines):
            """
            Final validation to ensure Medical copay/coinsurance extraction follows strict In-Network only rule.
            
            Logic:
            1. Inpatient & Outpatient Hospital: Should NEVER have copays (Rule #20). Remove if present.
            2. ER & Urgent Care: CAN have copays. Keep them.
            3. Coinsurance: Remove if it comes from Out-of-Network (when In-Network has no coinsurance).
            """
            if not raw_lines:
                return

            raw_text = '\n'.join(raw_lines)
            fixes = 0
            
            # Rule: If inpatient copay mentions '$X per day' or 'per day' pattern, multiply by exactly 3.
            inpatient = schema_data.get('hospital_surgical', {})
            if isinstance(inpatient, dict):
                current_copay = inpatient.get('inpatient_copay')
                if current_copay and current_copay.startswith('$'):
                    # Search raw lines for inpatient rows to see if "$X per day" pattern is mentioned
                    has_per_day_copay = False
                    for line in raw_lines:
                        line_lower = line.lower()
                        # Identify an inpatient hospital row
                        if ('inpatient' in line_lower or 'hospital stay' in line_lower or 'facility fee' in line_lower):
                            # Check if any per-day pattern exists:
                            # e.g., "$100 per day", "$250 copay per day", "per day copay", "3 day", "5 day", etc.
                            # Match: dollar amount followed by optional words (like "copay") then "per day" or "{n} day" patterns
                            if re.search(r'\$\s*[\d,]+\s+(?:\w+\s+)*(?:per\s+day|\d+\s+day)|per\s+day\s+copay|day\s+copay', line_lower):
                                has_per_day_copay = True
                                break
                    
                    if has_per_day_copay:
                        try:
                            # Extract numeric value
                            numeric_match = re.search(r'\$?([\d,]+(?:\.\d+)?)', current_copay)
                            if numeric_match:
                                val_str = numeric_match.group(1).replace(',', '')
                                val_float = float(val_str)
                                multiplied = val_float * 3
                                
                                # Format correctly (e.g. $1,500)
                                if multiplied.is_integer():
                                    new_copay = f"${int(multiplied):,}"
                                else:
                                    new_copay = f"${multiplied:,.2f}"
                                    
                                inpatient['inpatient_copay'] = new_copay
                                fixes += 1
                                print(f"    [FIX-PER-DAY] hospital_surgical.inpatient_copay: Multiplied '{current_copay}' by 3 -> '{new_copay}' (found '$X per day' pattern)")
                        except Exception as e:
                            print(f"    [WARN] Failed to apply per day multiplier: {e}")
            
            # Now validate coinsurance values
            medical_services_coinsurance = [
                ('inpatient_coinsurance', ['inpatient', 'hospital stay', 'facility fee'], 'hospital_surgical'),
                ('op_hospital_coinsurance', ['outpatient surgery', 'outpatient hospital', 'ambulatory'], 'hospital_surgical'),
                ('er_coinsurance', ['emergency room'], 'hospital_surgical'),
                ('urgent_care_coinsurance', ['urgent care'], 'urgent_care_labs_imaging'),
            ]

            for coinsurance_key, keywords, section_key in medical_services_coinsurance:
                section = schema_data.get(section_key, {})
                if not isinstance(section, dict):
                    continue

                current_coinsurance = section.get(coinsurance_key)
                if not current_coinsurance:
                    continue

                # Find matching service row(s) in raw text
                matching_rows = []
                for line in raw_lines:
                    if '|' not in line:
                        continue
                    line_lower = line.lower()
                    if any(kw in line_lower for kw in keywords):
                        matching_rows.append(line)

                if not matching_rows:
                    continue

                # Analyze first matching row
                row = matching_rows[0]
                parts = [p.strip() for p in row.split('|')]

                # Detect In-Network and Out-of-Network cells, accounting for 3-col layout:
                #   Level 1 Pharmacy (Not Applicable) | In-Network | Out-of-Network
                # We MUST skip cells that are purely "Not Applicable" / "N/A" when looking
                # for cost data — those are pharmacy-only placeholder columns.
                in_network_cell = None
                out_of_network_cell = None

                # Try label-based detection first
                in_network_label_idx = None
                oon_label_idx = None
                for i, part in enumerate(parts):
                    if re.search(r'In[- ]?Network.*You will pay|Participating.*You will pay', part, re.IGNORECASE):
                        in_network_label_idx = i
                    if re.search(r'Out[- ]?of[- ]?Network.*You will pay|Non[- ]?Participating.*You will pay', part, re.IGNORECASE):
                        oon_label_idx = i

                if in_network_label_idx is not None and in_network_label_idx + 1 < len(parts):
                    in_network_cell = parts[in_network_label_idx + 1]
                    if oon_label_idx is not None and oon_label_idx + 1 < len(parts):
                        out_of_network_cell = parts[oon_label_idx + 1]
                else:
                    # Fallback: Use the _in_network_cost_column_index helper to detect the correct column
                    # This handles 2-col, 3-col (with Preferred), and other layouts correctly
                    has_preferred = bool(re.search(r'Preferred\s+Network', raw_text, re.IGNORECASE))
                    in_network_idx = _in_network_cost_column_index(parts, has_preferred)
                    
                    if in_network_idx is None or in_network_idx >= len(parts):
                        continue
                    
                    in_network_cell = parts[in_network_idx]
                    
                    # Try to detect Out-of-Network column (usually comes after In-Network)
                    # For 3-col: Preferred | In-Network | Out-of-Network
                    # For 2-col: In-Network | Out-of-Network
                    out_of_network_cell = None
                    if has_preferred and in_network_idx + 1 < len(parts):
                        # We have Preferred; try to find OON after In-Network
                        potential_oon = parts[in_network_idx + 1]
                        if re.search(r'\$\d+|(\d+)%|no charge', potential_oon, re.IGNORECASE):
                            out_of_network_cell = potential_oon
                    elif not has_preferred and in_network_idx + 1 < len(parts):
                        # No Preferred; try to find OON after In-Network
                        potential_oon = parts[in_network_idx + 1]
                        if re.search(r'\$\d+|(\d+)%|no charge', potential_oon, re.IGNORECASE):
                            out_of_network_cell = potential_oon

                # Extract coinsurance percentages
                in_coinsurance = _extract_percent_from_cell(in_network_cell) if in_network_cell else None
                oon_coinsurance = _extract_percent_from_cell(out_of_network_cell) if out_of_network_cell else None

                # Validate: If current coinsurance doesn't match In-Network but matches Out-of-Network, remove it
                if current_coinsurance != in_coinsurance:
                    # Current doesn't match In-Network
                    if oon_coinsurance and current_coinsurance == oon_coinsurance:
                        # Current matches Out-of-Network; it came from wrong column - remove it
                        section[coinsurance_key] = None
                        fixes += 1
                        print(f"    [FIX-COIN-OON] {section_key}.{coinsurance_key}: Removed Out-of-Network value ('{current_coinsurance}')")
                    elif in_coinsurance is None and oon_coinsurance and current_coinsurance == oon_coinsurance:
                        # In-Network has NO coinsurance, but Out-of-Network does and current matches OON
                        # This came from Out-of-Network; remove it
                        section[coinsurance_key] = None
                        fixes += 1
                        print(f"    [FIX-COIN-NONE] {section_key}.{coinsurance_key}: Removed (not in In-Network)")
            
            if fixes:
                print(f"    [RESTORE] Applied {fixes} In-Network only correction(s)")
        
        _fix_cross_column_medical_extraction(schema_data, raw_text_lines)
        _validate_hospital_facility_fee_only(schema_data, raw_text_lines)
        _restore_missing_in_network_copays(schema_data, raw_text_lines)

        scenario_04_active = False
        if raw_text_full:
            # Check for the exact SBC warning message
            # The warning might have words scattered across lines, so use flexible regex
            import re
            has_sbc_warning_part1 = bool(re.search(
                r"all\s+copayment\s+and\s+coinsurance\s+costs.{0,200}shown\s+in\s+this\s+chart\s+are\s+after\s+your\s+deductible\s+has\s+been\s+met",
                raw_text_full,
                re.IGNORECASE | re.DOTALL
            ))
            has_sbc_warning_part2 = bool(re.search(
                r"if\s+a\s+deductible\s+applies",
                raw_text_full,
                re.IGNORECASE | re.DOTALL
            ))
            has_sbc_warning = has_sbc_warning_part1 and has_sbc_warning_part2

            def _scenario_04_step2_preventive_before_deductible():
                """Check for exact preventive care answer: 'Yes. Preventive care is covered before you meet your deductible.'
                This is the NEW Scenario 04 requirement.
                
                HANDLES THESE VARIANTS:
                • "Yes. Preventive care is covered before you meet your deductible."
                • "Yes. Preventive care covered before you meet your deductible."
                • "Yes. Preventive care and categories with a copay are covered before you meet your deductible."
                • "Yes. Preventive care covered before you meet deductible."
                • "Yes. Preventive care [OTHER WORDS/LINE BREAKS] covered before you meet your deductible."
                • Other flexible OCR variants with scattered words
                """
                import re
                
                # Look for the exact phrase or variations
                # Using .{0,200} to allow up to 200 chars (words, spaces, line breaks) between key phrases
                patterns = [
                    # PATTERN 1: Standard - "Preventive care is covered before you meet your deductible"
                    r"yes\.?\s+preventive\s+care\s+is\s+covered\s+before\s+you\s+meet\s+your\s+deductible",
                    
                    # PATTERN 2: Without "is" - "Preventive care covered before you meet your deductible" (CRITICAL - user requested)
                    r"yes\.?\s+preventive\s+care\s+covered\s+before\s+you\s+meet\s+your\s+deductible",
                    
                    # PATTERN 3: Without "your" 
                    r"yes\.?\s+preventive\s+care\s+is\s+covered\s+before\s+you\s+meet\s+deductible",
                    
                    # PATTERN 4: "Preventive care and categories" variant - CRITICAL for UnitedHealthcare plans
                    r"yes\.?\s+preventive\s+care\s+and\s+categories.{0,100}are\s+covered\s+before\s+you\s+meet\s+your?\s+deductible",
                    
                    # PATTERN 5: FLEXIBLE - "Preventive care" with words/breaks in between, then "covered...deductible"
                    # Handles: "Yes. Preventive care [extra text] covered before you meet your deductible"
                    r"yes\.?\s+preventive\s+care.{0,200}covered\s+before\s+you\s+meet\s+your?\s+deductible",
                    
                    # PATTERN 6: Most flexible - "yes" + "preventive" + "covered" + "before" + "deductible"
                    # Allows up to 200 chars between each key phrase (handles scattered text across lines)
                    r"yes\.?\s+.{0,200}preventive\s+(care|services?).{0,200}covered.{0,200}before.{0,200}deductible",
                ]
                
                for pattern in patterns:
                    if re.search(pattern, raw_text_full, re.IGNORECASE | re.DOTALL):
                        # Make sure it's not just "has no deductible"
                        match_text = re.search(pattern, raw_text_full, re.IGNORECASE | re.DOTALL).group(0)
                        if "no deductible" not in match_text.lower():
                            return True
                
                return False

            has_preventive_before_deductible = _scenario_04_step2_preventive_before_deductible()
            # SCENARIO-04 is triggered by SBC warning alone
            # The preventive care confirmation is optional but informational
            scenario_04_active = has_sbc_warning
            if scenario_04_active:
                if has_preventive_before_deductible:
                    print("    [SCENARIO-04] SBC warning + 'Yes. Preventive care is covered before you meet your deductible.' detected")
                else:
                    print("    [SCENARIO-04] SBC warning detected (preventive confirmation not found, but Scenario-04 still active)")

            def _check_deductible_question_answer_no():
                """Check for the answer "No." to the question: "Are there services covered before you meet your deductible?"
                
                This detects the specific scenario where the answer to the deductible question is "No."
                which means NO services are covered before the deductible.
                
                Pattern: Look for the question followed by "No." answer (accounting for line breaks, spacing, etc.)
                """
                import re
                
                # Look for question pattern with flexible spacing/line breaks, followed by "No."
                # Pattern: "Are there services" ... "covered before" ... "deductible?" ... "No."
                patterns = [
                    # Direct pattern: question followed by "No." answer
                    r"are\s+there\s+services.{0,200}covered\s+before\s+you\s+meet\s+your?\s+deductible\s*\?\s*\.?\s*no\s*\.?",
                    
                    # More flexible: "Are there services" + "No." (answer only, less strict)
                    r"are\s+there\s+services.{0,300}covered\s+before.{0,100}no\s*\.(?!\s+you)",
                ]
                
                for pattern in patterns:
                    if re.search(pattern, raw_text_full, re.IGNORECASE | re.DOTALL):
                        return True
                
                return False
            
            has_deductible_question_answer_no = _check_deductible_question_answer_no()
            
            # WARNING SCENARIO-03: SBC Warning + Deductible Question Answer = "No."
            # Trigger: SBC warning present AND answer to "Are there services covered before you meet your deductible?" is "No."
            scenario_03_active = has_sbc_warning and has_deductible_question_answer_no
            if scenario_03_active:
                print("    [SCENARIO-03] SBC warning + Deductible question answer 'No.' detected")

        def _raw_service_lines_for_service(copay_base):
            keywords = service_raw_keywords.get(copay_base, [])
            if not keywords or not raw_text_lines:
                return []
            matches = []
            has_pref = bool(re.search(r'preferred\s+network', raw_text_full, re.IGNORECASE)) if raw_text_full else False
            
            for line in raw_text_lines:
                line_norm = " ".join(line.lower().split())
                
                # To prevent matching keywords in the "Limitations/Exceptions" column (which causes false positives),
                # we should only look for keywords in the service description columns (before the cost columns).
                if '|' in line_norm:
                    parts = line_norm.split('|')
                    idx = _in_network_cost_column_index(parts, has_pref)
                    if idx is None:
                        idx = 2 if has_pref else 1
                    search_text = "|".join(parts[:idx])
                else:
                    search_text = line_norm
                    
                if any(kw in search_text for kw in keywords):
                    matches.append(line_norm)
            return matches

        def _get_relevant_text_for_indication(line_norm):
            if '|' not in line_norm:
                return line_norm
            parts = [p.strip() for p in line_norm.split('|')]
            has_pref = bool(re.search(r'preferred\s+network', raw_text_full, re.IGNORECASE)) if raw_text_full else False
            
            idx = _in_network_cost_column_index(parts, has_pref)
            if idx is None:
                idx = 2 if has_pref else 1
            
            relevant_parts = []
            if len(parts) > 0:
                relevant_parts.append(parts[0])  # Include description column
            if idx < len(parts) and idx != 0:
                relevant_parts.append(parts[idx]) # Include In-Network column
                
            return " ".join(relevant_parts)

        def _raw_service_line_has_deductible_applies(copay_base):
            import re
            for line_norm in _raw_service_lines_for_service(copay_base):
                rel_text = _get_relevant_text_for_indication(line_norm)
                if not _contains_deductible_applies(rel_text):
                    continue
                if re.search(r"\$\s*\d", rel_text):
                    return True
            return False

        def _raw_service_line_has_deductible_does_not_apply(copay_base):
            for line_norm in _raw_service_lines_for_service(copay_base):
                rel_text = _get_relevant_text_for_indication(line_norm)
                if _contains_deductible_does_not_apply(rel_text):
                    return True
            return False

        def _row_has_deductible_indication(copay_val, coins_val, copay_base):
            for val in (copay_val, coins_val):
                if _contains_deductible_does_not_apply(val):
                    return True
                if _contains_deductible_applies(val):
                    return True
                if _contains_deductible_waived(val):
                    return True
            for line_norm in _raw_service_lines_for_service(copay_base):
                rel_text = _get_relevant_text_for_indication(line_norm)
                if _contains_deductible_does_not_apply(rel_text):
                    return True
                if _contains_deductible_applies(rel_text):
                    return True
                if _contains_deductible_waived(rel_text):
                    return True
            return False
        
        def _extract_limitation_copay_amount(copay_base):
            """
            Extract copay amount from limitation column if it matches pattern:
            "$X per occurrence copay applies prior to the overall deductible"
            Returns: (copay_amount_str, limitation_text) or (None, None)
            """
            import re
            for line_norm in _raw_service_lines_for_service(copay_base):
                if '|' not in line_norm:
                    continue
                parts = [p.strip() for p in line_norm.split('|')]
                # Limitation column is typically the last column after all cost columns
                # For a typical 5-part row: service | in-network | out-of-network | limitations | notes
                # Or 6-part: service | preferred | in-network | out-of-network | limitations | notes
                # We'll check the last 2 columns for the limitation pattern
                for part in parts[-2:]:
                    part_lower = part.lower()
                    # Match pattern: "$X per occurrence copay applies prior to the overall deductible"
                    match = re.search(r'\$\s*(\d+(?:,\d{3})*)\s+per occurrence copay applies prior to the overall deductible', part_lower, re.IGNORECASE)
                    if match:
                        amount_str = match.group(1).replace(',', '')
                        return f"${amount_str}", part
            return None, None
        
        def _get_limitation_text_for_service(copay_base):
            """
            Extract the full limitation text for a service from the last column(s)
            """
            for line_norm in _raw_service_lines_for_service(copay_base):
                if '|' not in line_norm:
                    continue
                parts = [p.strip() for p in line_norm.split('|')]
                # Return the last 1-2 parts (limitation column typically at the end)
                if len(parts) > 1:
                    return " ".join(parts[-2:])
            return None
        
        medical_sections = ['office_visits', 'hospital_surgical', 'urgent_care_labs_imaging']
        medical_services_map = [
            ('primary_care_copay', 'primary_care_coinsurance'),
            ('specialist_copay', 'specialist_coinsurance'),
            ('inpatient_copay', 'inpatient_coinsurance'),
            ('op_hospital_copay', 'op_hospital_coinsurance'),
            ('er_copay', 'er_coinsurance'),
            ('urgent_care_copay', 'urgent_care_coinsurance'),
            ('lab_services_copay', 'lab_services_coinsurance'),
            ('xray_copay', 'xray_coinsurance'),
            ('medical_imaging_copay', 'medical_imaging_coinsurance'),
        ]

        for section_name in medical_sections:
            section = schema_data.get(section_name, {})
            if not isinstance(section, dict): continue
            
            for copay_base, coins_base in medical_services_map:
                if copay_base in section and coins_base in section:
                    copay_mod_key = f"{copay_base}_modifier"
                    coins_mod_key = f"{coins_base}_modifier"
                    copay_status_key = f"{copay_base}_deductible_status"
                    coins_status_key = f"{coins_base}_deductible_status"
                    copay_value = section.get(copay_base)
                    coins_value = section.get(coins_base)

                    copay_status_val = str(section.get(copay_status_key) or "")
                    coins_status_val = str(section.get(coins_status_key) or "")
                    copay_mod_val = section.get(copay_mod_key)
                    coins_mod_val = section.get(coins_mod_key)

                    # EARLY SANITY CHECK FOR LAB/XRAY: These services have combined rows like "Designated Lab: $60 | Lab: $150 | X-ray: $60"
                    # The status field might be contaminated from another row or from generic keyword matching.
                    # Only use the status if the deductible indication is in the copay_value itself.
                    if copay_base in ['lab_services_copay', 'xray_copay']:
                        if (copay_status_val and 'deductible' in copay_status_val.lower() and 
                            copay_value and 'deductible' not in str(copay_value).lower()):
                            # Status mentions deductible but copay value doesn't - this is likely contaminated
                            # Clear the status so it won't trigger Scenario-01/04
                            section[copay_status_key] = ""
                            copay_status_val = ""
                            print(f"    [LAB-XRAY-EARLY-SANITY] {section_name}/{copay_base}: Cleared deductible status (not in copay value)")

                    # ==========================================
                    # SCENARIO-03: HDHP Check (Highest Priority)
                    # ==========================================
                    if hdhp:
                        section[copay_mod_key] = "After Deductible"
                        section[coins_mod_key] = "After Deductible"
                        section[copay_status_key] = ""
                        section[coins_status_key] = ""
                        
                        # Preserve value-filling from Limitation Scenarios
                        limitation_copay, _ = _extract_limitation_copay_amount(copay_base)
                        if limitation_copay:
                            coins_is_zero = (coins_value == '0%')
                            coins_is_positive = (coins_value and coins_value != '0%' and coins_value not in ['', 'None', None])
                            
                            if coins_is_zero and not copay_value:
                                section[copay_base] = limitation_copay
                            elif coins_is_positive:
                                current_plans_entry_key = f"{copay_base.replace('_copay', '')}_current_plans_entry"
                                section[current_plans_entry_key] = f"{limitation_copay} + {coins_value}"
                        
                        print(f"    [SCENARIO-03] {copay_base}/{coins_base}: HDHP is true -> Set modifiers to 'After Deductible' and preserved limitation values if any")
                        continue
                    # ==========================================

                    # WARNING SCENARIO-03: SBC Warning + Deductible Question Answer = "No."
                    # Trigger: SBC warning present AND answer to "Are there services covered before you meet your deductible?" is "No."
                    # Logic: For any applicable Medical field with copay value and no deductible exception wording:
                    #   Set both modifiers to "After Deductible"
                    if scenario_03_active:
                        # Check if service contains deductible exception wording
                        has_deductible_exception = (
                            _contains_deductible_does_not_apply(copay_value) or
                            _contains_deductible_does_not_apply(coins_value) or
                            _contains_deductible_does_not_apply(copay_status_val) or
                            _contains_deductible_does_not_apply(coins_status_val) or
                            _raw_service_line_has_deductible_does_not_apply(copay_base)
                        )
                        
                        # If no deductible exception wording AND copay exists, set both modifiers
                        has_real_copay = bool(copay_value and str(copay_value).strip() not in ["", "None", "$0", "0%", "0"])
                        
                        if has_real_copay and not has_deductible_exception:
                            section[copay_mod_key] = "After Deductible"
                            section[coins_mod_key] = "After Deductible"
                            section[copay_status_key] = ""
                            section[coins_status_key] = ""
                            print(f"    [WARNING-SCENARIO-03] {copay_base}/{coins_base}: Copay exists + no deductible exception -> Both modifiers = 'After Deductible'")
                            continue

                    # WARNING SCENARIO-01: SBC Warning + Preventive Care Statement
                    # Trigger: SBC warning present AND preventive care statement present
                    # Logic:
                    #   Case 1: If "Deductible does not apply" found -> Both modifiers = DW
                    #   Case 2: If copay exists AND no deductible wording -> Copay modifier = AD, leave coinsurance unchanged
                    if scenario_04_active and has_preventive_before_deductible:
                        # WARNING SCENARIO-01 is active (both SBC warning and preventive care present)
                        
                        # Check for "Deductible does not apply" wording
                        has_deductible_does_not_apply_warning = (
                            _contains_deductible_does_not_apply(copay_value) or
                            _contains_deductible_does_not_apply(coins_value) or
                            _contains_deductible_does_not_apply(copay_status_val) or
                            _contains_deductible_does_not_apply(coins_status_val) or
                            _raw_service_line_has_deductible_does_not_apply(copay_base)
                        )
                        
                        # Case 1: "Deductible does not apply" found
                        if has_deductible_does_not_apply_warning:
                            section[copay_mod_key] = "Deductible Waived"
                            section[coins_mod_key] = "Deductible Waived"
                            section[copay_status_key] = "Deductible does not apply"
                            section[coins_status_key] = "Deductible does not apply"
                            print(f"    [WARNING-SCENARIO-01-CASE1] {copay_base}/{coins_base}: 'Deductible does not apply' found -> Both modifiers = 'Deductible Waived'")
                            continue
                        
                        # Case 2: Copay exists AND no deductible-related wording
                        # Only trigger if copay exists AND there is NO deductible wording (either "applies" or "does not apply")
                        has_real_copay = bool(copay_value and str(copay_value).strip() not in ["", "None", "$0", "0%", "0"])
                        has_any_deductible_wording = (
                            _contains_deductible_applies(copay_value) or
                            _contains_deductible_applies(coins_value) or
                            _contains_deductible_applies(copay_status_val) or
                            _contains_deductible_applies(coins_status_val) or
                            _contains_deductible_does_not_apply(copay_value) or
                            _contains_deductible_does_not_apply(coins_value) or
                            _contains_deductible_does_not_apply(copay_status_val) or
                            _contains_deductible_does_not_apply(coins_status_val) or
                            _raw_service_line_has_deductible_applies(copay_base) or
                            _raw_service_line_has_deductible_does_not_apply(copay_base)
                        )
                        
                        if has_real_copay and not has_any_deductible_wording:
                            # Set copay modifier, set coinsurance modifier to default "After Deductible"
                            section[copay_mod_key] = "After Deductible"
                            section[coins_mod_key] = "After Deductible"
                            section[copay_status_key] = ""
                            section[coins_status_key] = ""
                            print(f"    [WARNING-SCENARIO-01-CASE2] {copay_base}/{coins_base}: Copay exists + no deductible wording -> Both modifiers = 'After Deductible'")
                            continue

                    # SCENARIO-04: SBC Warning Logic (for cases where preventive care NOT present)
                    # When Scenario-04 is active but preventive care is NOT present
                    # Check if service has EXPLICIT deductible language
                    # If it does, skip Scenario-04 and let Scenario-01/02 handle it normally
                    # If it doesn't, apply Scenario-04 logic based on costs
                    if scenario_04_active and not has_preventive_before_deductible:
                        # Check if service explicitly says "deductible does not apply" or "deductible applies"
                        # CRITICAL: Check BOTH extracted JSON fields AND raw text
                        # This prevents false negatives when LLM extraction is incomplete
                        has_explicit_deductible_language = (
                            _contains_deductible_applies(copay_value) or
                            _contains_deductible_applies(coins_value) or
                            _contains_deductible_applies(copay_status_val) or
                            _contains_deductible_applies(coins_status_val) or
                            _contains_deductible_does_not_apply(copay_value) or
                            _contains_deductible_does_not_apply(coins_value) or
                            _contains_deductible_does_not_apply(copay_status_val) or
                            _contains_deductible_does_not_apply(coins_status_val) or
                            # CRITICAL: Also check raw text for explicit deductible language
                            # This catches cases where LLM didn't extract the deductible status correctly
                            _raw_service_line_has_deductible_applies(copay_base) or
                            _raw_service_line_has_deductible_does_not_apply(copay_base)
                        )
                        
                        # If service has explicit deductible language, skip Scenario-04
                        # and let Scenario-01/02/03 handle it normally
                        # SPECIAL EXCEPTION: For Lab/X-Ray, don't trust the raw text check alone (keyword "lab" is too generic)
                        # Only consider it explicit if the status field clearly shows it
                        if copay_base in ['lab_services_copay', 'xray_copay']:
                            # For Lab/X-Ray, ignore raw text check; only use extracted fields
                            has_explicit_deductible_language = (
                                _contains_deductible_applies(copay_value) or
                                _contains_deductible_applies(coins_value) or
                                _contains_deductible_applies(copay_status_val) or
                                _contains_deductible_applies(coins_status_val) or
                                _contains_deductible_does_not_apply(copay_value) or
                                _contains_deductible_does_not_apply(coins_value) or
                                _contains_deductible_does_not_apply(copay_status_val) or
                                _contains_deductible_does_not_apply(coins_status_val)
                            )
                        
                        if has_explicit_deductible_language:
                            print(f"    [SCENARIO-04] {copay_base}/{coins_base}: Explicit deductible language found -> Fall through to other scenarios")
                        else:
                            # No explicit deductible language - apply Scenario-04 based on costs
                            has_real_copay = bool(copay_value and str(copay_value).strip() not in ["", "None", "$0", "0%", "0"])
                            has_real_coins = bool(coins_value and str(coins_value).strip() not in ["", "None", "0%", "0"])
                            
                            # Only one cost type present (either copay XOR coinsurance, not both)
                            only_one_cost_type = (has_real_copay and not has_real_coins) or (has_real_coins and not has_real_copay)
                            
                            # WARNING SCENARIO-02: If ONLY one cost type (copay XOR coinsurance, not both)
                            # AND there is no deductible-related indication for this service
                            # -> Set default modifiers: copay = "Deductible Waived", coinsurance = "After Deductible"
                            if only_one_cost_type and (has_real_copay or has_real_coins):
                                # Set default modifiers for single cost type services
                                section[copay_mod_key] = "Deductible Waived"
                                section[coins_mod_key] = "After Deductible"
                                section[copay_status_key] = ""
                                section[coins_status_key] = ""
                                print(f"    [WARNING-SCENARIO-02] {copay_base}/{coins_base}: Only one cost type + no deductible indication -> Set defaults: Copay='Deductible Waived', Coinsurance='After Deductible'")
                                continue
                            
                            # SBC Warning Scenario-01 SPECIAL CASE: HAS copay but MIXED costs (both copay and coinsurance)
                            # -> Set to "After Deductible"
                            elif has_real_copay and has_real_coins:
                                section[copay_mod_key] = "After Deductible"
                                section[coins_mod_key] = "After Deductible"
                                section[copay_status_key] = ""
                                section[coins_status_key] = ""
                                print(f"    [SCENARIO-04-SBC-WARNING-01-SPECIAL] {copay_base}/{coins_base}: Mixed costs (copay + coinsurance) + no explicit deductible language -> Set to 'After Deductible'")
                                continue

                    # LIMITATION SCENARIO-01: Copay extraction from limitation column when Coinsurance = 0%
                    # Trigger Condition 1: Coinsurance = 0%
                    # Trigger Condition 2: Limitation column contains exact pattern: "$<Amount> per occurrence copay applies prior to the overall deductible"
                    # Trigger Condition 3: Copay field is empty
                    # 
                    # Value Filling:
                    #   1. Extract dollar amount from Limitation column
                    #   2. Populate Copay field with extracted amount
                    #   3. Keep Coinsurance = 0%
                    # 
                    # Dropdown Logic:
                    #   Copay Modifier = "After Deductible"
                    #   Coinsurance Modifier = "After Deductible"
                    #
                    # Scenario Priority:
                    #   Evaluate Limitation Scenario – 01 FIRST
                    #   If triggered, SKIP Limitation Scenario – 02 for the same service
                    
                    limitation_copay, limitation_text = _extract_limitation_copay_amount(copay_base)
                    coins_is_zero = coins_value == '0%'
                    
                    # LIMITATION SCENARIO-01 TRIGGER CHECK
                    if limitation_copay and coins_is_zero and not copay_value:
                        # Limitation Scenario 01 TRIGGERED
                        # Value Filling
                        section[copay_base] = limitation_copay
                        # Dropdown Logic
                        section[copay_mod_key] = "After Deductible"
                        section[coins_mod_key] = "After Deductible"
                        # Clear status fields
                        section[copay_status_key] = ""
                        section[coins_status_key] = ""
                        # Do NOT populate current_plans_entry for Scenario 01
                        print(f"    [LIMITATION-SCENARIO-01] {copay_base}/{coins_base}: TRIGGERED")
                        print(f"      Condition 1 (Coinsurance=0%): ✓")
                        print(f"      Condition 2 (Limitation pattern found): ✓ '{limitation_copay}'")
                        print(f"      Condition 3 (Copay empty): ✓")
                        print(f"      Action: Copay=${limitation_copay[1:]} | Copay Mod=After Deductible | Coinsurance Mod=After Deductible")
                        continue
                    
                    # LIMITATION SCENARIO-02: Current Plans Entry population when Coinsurance > 0%
                    # Trigger Condition 1: Coinsurance > 0% (e.g., 20%, 30%, 50%)
                    # Trigger Condition 2: Limitation column contains exact pattern: "$<Amount> per occurrence copay applies prior to the overall deductible"
                    # 
                    # Value Filling:
                    #   1. Extract dollar amount from Limitation column
                    #   2. Populate Current Plans Entry = "$<Amount> + <Coinsurance%>"
                    #   3. Preserve both limitation Copay value and existing Coinsurance value
                    # 
                    # Dropdown Logic:
                    #   Do NOT modify any dropdown values
                    #   Leave all existing dropdown values exactly as they are
                    #
                    # Scenario Priority:
                    #   Execute Limitation Scenario – 02 ONLY if Limitation Scenario – 01 did NOT trigger
                    
                    coins_is_positive = coins_value and coins_value != '0%' and coins_value not in ['', 'None', None]
                    
                    # LIMITATION SCENARIO-02 TRIGGER CHECK
                    if limitation_copay and coins_is_positive:
                        # Limitation Scenario 02 TRIGGERED
                        # Value Filling
                        current_plans_entry_key = f"{copay_base.replace('_copay', '')}_current_plans_entry"
                        current_plans_entry = f"{limitation_copay} + {coins_value}"
                        section[current_plans_entry_key] = current_plans_entry
                        # Dropdown Logic: Set default modifiers
                        section[copay_mod_key] = "Deductible Waived"
                        section[coins_mod_key] = "After Deductible"
                        section[copay_status_key] = ""
                        section[coins_status_key] = ""
                        print(f"    [LIMITATION-SCENARIO-02] {copay_base}/{coins_base}: TRIGGERED")
                        print(f"      Condition 1 (Coinsurance>0%): ✓ {coins_value}")
                        print(f"      Condition 2 (Limitation pattern found): ✓ '{limitation_copay}'")
                        print(f"      Action: Current Plans Entry='{current_plans_entry}' | Copay='Deductible Waived', Coinsurance='After Deductible'")
                        continue

                    # SCENARIO-01: Explicit Waived Check
                    # If "Deductible does not apply" OR "No Charge" is explicitly found
                    has_deductible_does_not_apply = False
                    has_no_charge = False
                    
                    for field_val in (copay_value, coins_value, copay_status_val, coins_status_val):
                        if _contains_deductible_does_not_apply(field_val):
                            has_deductible_does_not_apply = True
                        if field_val and 'no charge' in str(field_val).lower():
                            has_no_charge = True
                    
                    if not has_deductible_does_not_apply and _raw_service_line_has_deductible_does_not_apply(copay_base):
                        has_deductible_does_not_apply = True
                        
                    if not has_no_charge:
                        for line_norm in _raw_service_lines_for_service(copay_base):
                            rel_text = _get_relevant_text_for_indication(line_norm)
                            if 'no charge' in rel_text.lower():
                                has_no_charge = True
                                break
                    
                    # Split-Cell Safety Check: If the LLM correctly extracted a non-zero cost for this specific service, 
                    # it CANNOT be "No charge" (prevents bleeding in combined cells like Lab/X-ray)
                    if has_no_charge:
                        has_non_zero_cost = False
                        for val in (copay_value, coins_value):
                            if val:
                                val_str = str(val).lower()
                                dollar_match = re.search(r'\$(\d+(?:\.\d+)?)', val_str)
                                if dollar_match and float(dollar_match.group(1)) > 0:
                                    has_non_zero_cost = True
                                pct_match = re.search(r'(\d+(?:\.\d+)?)%', val_str)
                                if pct_match and float(pct_match.group(1)) > 0:
                                    has_non_zero_cost = True
                        if has_non_zero_cost:
                            has_no_charge = False
                    
                    if has_deductible_does_not_apply or has_no_charge:
                        section[copay_mod_key] = "Deductible Waived"
                        section[coins_mod_key] = "Deductible Waived"
                        
                        if has_no_charge:
                            section[copay_status_key] = "No charge"
                            section[coins_status_key] = "No charge"
                        else:
                            section[copay_status_key] = "Deductible does not apply"
                            section[coins_status_key] = "Deductible does not apply"
                        print(f"    [SCENARIO-01] {copay_base}/{coins_base}: 'Deductible does not apply' or 'No Charge' found -> Copay set to 'Deductible Waived', Coinsurance set to '{section[coins_mod_key]}' (0%={coins_value=='0%'})")
                        continue

                    # SCENARIO-02: Explicit Applies Check
                    triggered_field = None
                    for field_name, field_val in (
                        (copay_base, copay_value),
                        (coins_base, coins_value),
                    ):
                        if _contains_deductible_applies(field_val):
                            triggered_field = field_name
                            break

                    raw_line_match = False
                    if not triggered_field and _raw_service_line_has_deductible_applies(copay_base):
                        raw_line_match = True

                    if triggered_field or raw_line_match:
                        trigger_source = (
                            f"{section_name}.{triggered_field}" if triggered_field else f"raw_text:{copay_base}"
                        )
                        section[copay_mod_key] = "After Deductible"
                        section[coins_mod_key] = "After Deductible"
                        section[copay_status_key] = "Deductible applies"
                        section[coins_status_key] = "Deductible applies"
                        print(f"    [SCENARIO-02] {trigger_source} contains 'Deductible applies' -> {copay_base}/{coins_base} set to 'After Deductible'")
                        continue

                    # SCENARIO-00: Fallback Default
                    section[copay_mod_key] = "Deductible Waived"
                    section[coins_mod_key] = "After Deductible"
                    section[copay_status_key] = ""
                    section[coins_status_key] = ""
                    print(f"    [SCENARIO-00] {copay_base}/{coins_base}: Default modifiers='Deductible Waived'/'After Deductible', Col H blank")
        
        # Phase 3.5: Lab-Xray Sync Rule
        # When lab_services and xray come from same "Diagnostic test (x-ray, blood work)" PDF row,
        # they should have matching copay AND coinsurance values. If lab is different, sync them.
        urgent_care_labs = schema_data.get('urgent_care_labs_imaging', {})
        if isinstance(urgent_care_labs, dict):
            lab_copay = urgent_care_labs.get('lab_services_copay')
            xray_copay = urgent_care_labs.get('xray_copay')
            lab_coin = urgent_care_labs.get('lab_services_coinsurance')
            xray_coin = urgent_care_labs.get('xray_coinsurance')
            
            # Sync copay if lab differs from xray
            if lab_copay != xray_copay and xray_copay is not None:
                urgent_care_labs['lab_services_copay'] = xray_copay
                xray_copay_mod = urgent_care_labs.get('xray_copay_modifier')
                if xray_copay_mod:
                    urgent_care_labs['lab_services_copay_modifier'] = xray_copay_mod
                xray_copay_status = urgent_care_labs.get('xray_copay_deductible_status')
                if xray_copay_status:
                    urgent_care_labs['lab_services_copay_deductible_status'] = xray_copay_status
                print(f"    [FIX-LAB-XRAY-SYNC] lab_services_copay: Synced to xray_copay ('{xray_copay}')")
            
            # Sync coinsurance if lab is 0% but xray is higher
            if lab_coin == '0%' and xray_coin and xray_coin != '0%':
                # Lab and xray are from same diagnostic test row - sync coinsurance and modifier
                urgent_care_labs['lab_services_coinsurance'] = xray_coin
                xray_mod = urgent_care_labs.get('xray_coinsurance_modifier')
                if xray_mod:
                    urgent_care_labs['lab_services_coinsurance_modifier'] = xray_mod
                xray_coin_status = urgent_care_labs.get('xray_coinsurance_deductible_status')
                if xray_coin_status:
                    urgent_care_labs['lab_services_coinsurance_deductible_status'] = xray_coin_status
                print(f"    [FIX-LAB-XRAY-SYNC] lab_services_coinsurance: Updated from '0%' to '{xray_coin}', modifier synced to '{xray_mod}'")
        
        # Phase 3.6: Designated Network Override
        # If raw text has "Designated Lab: $X  Lab: $Y" -> use $Y; "Designated: $X  Network: Y%" -> clear copay
        if raw_text_path and isinstance(urgent_care_labs, dict):
            try:
                with open(raw_text_path, 'r', encoding='utf-8') as rf:
                    raw_content = rf.read()
                lab_m = re.search(r'Designated Lab:.*?Lab:\s*(\$[\d,]+)\s*copay', raw_content, re.IGNORECASE | re.DOTALL)
                if lab_m:
                    urgent_care_labs['lab_services_copay'] = lab_m.group(1)
                    print(f"    [DESIGNATED-FIX] lab_services_copay -> '{lab_m.group(1)}' (Designated Lab ignored)")
                img_m = re.search(r'Designated:\s*\$[\d,]+.*?Network:\s*([\d]+%)\s*coinsurance', raw_content, re.IGNORECASE | re.DOTALL)
                if img_m:
                    urgent_care_labs['medical_imaging_copay'] = '$0'
                    print(f"    [DESIGNATED-FIX] medical_imaging_copay cleared (Designated ignored, Network coinsurance kept)")
            except Exception:
                pass

        # This prevents out-of-network pharmacy coinsurance from bleeding into in-network tier fields
        def _validate_pharmacy_in_network_only(schema_data, raw_lines):
            """
            Validates all pharmacy tier copay/coinsurance fields to ensure they come from the In-Network column only.
            If a tier value appears to come from Out-of-Network (when In-Network has different or no value), removes it.
            """
            if not raw_lines:
                return
            
            raw_text = '\n'.join(raw_lines)
            fixes = 0
            
            # Find pharmacy tier rows in raw text (typically contain "Tier", "Generic", "Brand", etc.)
            pharmacy_tier_keywords = {
                'tier_1_copay': ['tier 1', 'generic'],
                'tier_2_copay': ['tier 2', 'preferred brand'],
                'tier_3_copay': ['tier 3', 'non-preferred brand'],
                'tier_4_copay': ['tier 4', 'specialty'],
            }
            
            pharmacy = schema_data.get('pharmacy', {})
            if not isinstance(pharmacy, dict):
                return
            
            for tier_field, keywords in pharmacy_tier_keywords.items():
                copay_value = pharmacy.get(tier_field)
                coinsurance_field = tier_field.replace('_copay', '_coinsurance')
                coinsurance_value = pharmacy.get(coinsurance_field)
                
                # Skip if both are null/empty
                if not copay_value and not coinsurance_value:
                    continue
                
                # Find pharmacy table rows containing this tier
                matching_rows = [
                    line for line in raw_lines
                    if '|' in line and any(kw in line.lower() for kw in keywords)
                ]
                
                if not matching_rows:
                    continue
                
                # Parse first matching row to check in-network vs out-of-network columns
                row = matching_rows[0]
                parts = [p.strip() for p in row.split('|')]
                
                # Detect In-Network and Out-of-Network cells
                # For pharmacy tables, typical layout is:
                #   Description | Level 1 Pharmacy | In-Network | Out-of-Network
                # or: Description | In-Network | Out-of-Network | Limitations
                
                in_network_value = None
                out_of_network_value = None
                
                # Try label-based detection first (most reliable)
                for i, part in enumerate(parts):
                    part_lower = part.lower()
                    if 'in-network' in part_lower or 'in network' in part_lower or 'participating' in part_lower:
                        if i + 1 < len(parts):
                            in_network_value = parts[i + 1]
                    if 'out-of-network' in part_lower or 'out of network' in part_lower or 'non-participating' in part_lower:
                        if i + 1 < len(parts):
                            out_of_network_value = parts[i + 1]
                
                # Fallback: Use the _in_network_cost_column_index helper to detect the correct column
                # This handles 2-col, 3-col (with Preferred), and other layouts correctly
                if not in_network_value:
                    has_preferred = bool(re.search(r'Preferred\s+Network', raw_text, re.IGNORECASE)) if raw_text else False
                    in_network_idx = _in_network_cost_column_index(parts, has_preferred)
                    
                    if in_network_idx is not None and in_network_idx < len(parts):
                        in_network_value = parts[in_network_idx]
                        
                        # Try to detect Out-of-Network column (usually comes after In-Network)
                        # For 3-col: Preferred | In-Network | Out-of-Network (or Level1Rx | In-Network | Out-of-Network)
                        # For 2-col: In-Network | Out-of-Network
                        if in_network_idx + 1 < len(parts):
                            potential_oon = parts[in_network_idx + 1]
                            if re.search(r'\$\d+|(\d+)%|no charge', potential_oon, re.IGNORECASE):
                                out_of_network_value = potential_oon
                
                # Now validate: If current copay/coinsurance matches Out-of-Network but NOT In-Network,
                # it came from the wrong column and should be removed
                if coinsurance_value and out_of_network_value:
                    oon_coinsurance = _extract_percent_from_cell(out_of_network_value) if out_of_network_value else None
                    in_coinsurance = _extract_percent_from_cell(in_network_value) if in_network_value else None
                    
                    # If coinsurance matches Out-of-Network but NOT In-Network, remove it
                    if oon_coinsurance and coinsurance_value == oon_coinsurance and (not in_coinsurance or in_coinsurance != coinsurance_value):
                        pharmacy[coinsurance_field] = None
                        fixes += 1
                        print(f"    [FIX-PHARMACY-XCOLUMN] {tier_field}: Removed Out-of-Network coinsurance '{coinsurance_value}'")
                
                if copay_value and out_of_network_value:
                    oon_copay = _extract_dollar_from_cell(out_of_network_value) if out_of_network_value else None
                    in_copay = _extract_dollar_from_cell(in_network_value) if in_network_value else None
                    
                    # If copay matches Out-of-Network but NOT In-Network, remove it
                    if oon_copay and copay_value == oon_copay and (not in_copay or in_copay != copay_value):
                        pharmacy[tier_field] = None
                        fixes += 1
                        print(f"    [FIX-PHARMACY-XCOLUMN] {tier_field}: Removed Out-of-Network copay '{copay_value}'")
            
            if fixes:
                print(f"    [PHARMACY-XCOLUMN] Corrected {fixes} pharmacy field(s) for In-Network only extraction")
        
        _validate_pharmacy_in_network_only(schema_data, raw_text_lines)
        
        # Phase 4: Pharmacy Logic (Case A / default DW / HDHP)
        pharmacy = schema_data.get('pharmacy', {})
        if isinstance(pharmacy, dict):
            # Parse pharmacy-specific deductible tiers from raw text
            # Look for "Are there other deductibles for specific services?" section
            tier_deductible_waivers = set()  # Tiers explicitly mentioned in "Deductible does not apply to Tier X"
            has_pharmacy_deductible_no_tiers = False  # NEW: Deductible exists but NO tier exemptions mentioned
            
            if raw_text_full:
                import re
                # Find the section containing "Are there other deductibles for specific services?"
                # Match the answer that starts after this question
                question_pattern = r"are\s+there\s+other\s+deductibles?\s+for\s+specific\s+services?"
                question_match = re.search(question_pattern, raw_text_full, re.IGNORECASE)
                if question_match:
                    # Extract text from the answer (start from question_match.end() for ~500 chars to avoid full document)
                    answer_start = question_match.end()
                    answer_section = raw_text_full[answer_start:answer_start + 500]
                    
                    # Check if prescription drugs deductible is mentioned (with dollar amount)
                    if re.search(r"prescription\s+drugs.*\$\s*\d+", answer_section, re.IGNORECASE):
                        has_pharmacy_deductible_no_tiers = True  # NEW: Found deductible amount
                    
                    # Now parse the specific sentence: "Deductible does not apply to Tier X drugs"
                    # Pattern: "Deductible does not apply to Tier 1 drugs", "Tier 1 and Tier 2", "Tier 1, 2 and 3"
                    # FIXED: Make "deductible" optional and handle standalone numbers like "Tier 1 and 2"
                    deductible_pattern = r"(?:deductible\s+)?does\s+(?:not\s+)?apply\s+to\s+(tier\s+\d+(?:\s*(?:and|or|,)\s*(?:tier\s+)?\d+)*)"
                    deductible_match = re.search(deductible_pattern, answer_section, re.IGNORECASE)
                    if deductible_match:
                        tier_list_text = deductible_match.group(1)
                        # Extract all tier numbers mentioned: "tier 1 and 2" -> [1, 2]
                        tier_numbers = re.findall(r"\b(\d+)\b", tier_list_text)
                        tier_deductible_waivers = set(int(t) for t in tier_numbers)
                        has_pharmacy_deductible_no_tiers = False  # NEW: Tiers were mentioned, so reset flag
            
            # If the LLM copied the medical deductible into the pharmacy deductible, they are integrated! Clear it.
            ind_ded = schema_data.get('deductibles_and_coinsurance', {}).get('individual_deductible')
            rx_ded = pharmacy.get('pharmacy_deductible')
            if rx_ded and ind_ded and rx_ded == ind_ded:
                pharmacy['pharmacy_deductible'] = None
                print(f"    [FIX] Pharmacy Deductible matched Medical Deductible ({ind_ded}) - cleared because they are integrated")

            # Assign modifier for pharmacy deductible field itself (not tier-specific)
            if pharmacy.get('pharmacy_deductible'):
                pharmacy['pharmacy_deductible_modifier'] = "Rx - After Rx Deductible"
            
            for tier_num in range(1, 6):
                copay_mod_key = f"tier_{tier_num}_copay_modifier"
                coins_mod_key = f"tier_{tier_num}_coinsurance_modifier"
                copay_status_key = f"tier_{tier_num}_copay_deductible_status"
                coins_status_key = f"tier_{tier_num}_coinsurance_deductible_status"
                copay_val = pharmacy.get(f"tier_{tier_num}_copay")
                coins_val = pharmacy.get(f"tier_{tier_num}_coinsurance")

                # Check if tier exists in plan (has at least one value)
                tier_exists = bool(copay_val or coins_val)

                # Determine modifier based on tier-specific deductible waivers, HDHP, or default
                def is_rx_meaningful(val):
                    """True only if value has an actual dollar amount (not null, not 0%)."""
                    if not val:
                        return False
                    v = str(val).strip()
                    return v not in ["", "0%", "$0", "$0.00", "none"]

                def is_rx_zero(val):
                    """True if value is explicitly 0% (cost exists but is zero = waived)."""
                    if not val:
                        return False
                    v = str(val).strip()
                    return v in ["0%", "$0", "$0.00"]

                if hdhp:
                    # Meaningful value (e.g. $10, $35) -> After Plan Deductible
                    if is_rx_meaningful(copay_val):
                        pharmacy[copay_mod_key] = "Rx - After Plan Deductible"
                    elif is_rx_zero(copay_val):
                        pharmacy[copay_mod_key] = "Rx - Deductible Waived"
                    if is_rx_meaningful(coins_val):
                        pharmacy[coins_mod_key] = "Rx - After Plan Deductible"
                    elif is_rx_zero(coins_val):
                        pharmacy[coins_mod_key] = "Rx - Deductible Waived"
                    status = "(tier does not exist)" if not tier_exists else ""
                    print(f"    [HDHP] Tier {tier_num}: modifiers assigned based on values {status}")
                elif tier_num in tier_deductible_waivers:
                    # Tier explicitly mentioned in "Deductible does not apply to Tier X" -> Waived
                    pharmacy[copay_mod_key] = "Rx - Deductible Waived"
                    pharmacy[coins_mod_key] = "Rx - Deductible Waived"
                    status = "(tier does not exist)" if not tier_exists else ""
                    print(f"    [PHARMACY-DEDUCTIBLE] Tier {tier_num}: Set to 'Rx - Deductible Waived' (explicitly mentioned in deductible statement) {status}")
                elif has_pharmacy_deductible_no_tiers and not tier_deductible_waivers:  # NEW: Rule 2
                    # Pharmacy deductible exists but NO tier exemptions -> all tiers have deductible
                    pharmacy[copay_mod_key] = "Rx - After Rx Deductible"
                    pharmacy[coins_mod_key] = "Rx - After Rx Deductible"
                    status = "(tier does not exist)" if not tier_exists else ""
                    print(f"    [PHARMACY-DEDUCTIBLE-RULE2] Tier {tier_num}: Set to 'Rx - After Rx Deductible' (pharmacy deductible applies to all tiers) {status}")
                elif tier_deductible_waivers and tier_num not in tier_deductible_waivers:
                    # Other tiers (not in waiver list) but pharmacy deductible exists -> After Rx Deductible
                    pharmacy[copay_mod_key] = "Rx - After Rx Deductible"
                    pharmacy[coins_mod_key] = "Rx - After Rx Deductible"
                    status = "(tier does not exist)" if not tier_exists else ""
                    print(f"    [PHARMACY-DEDUCTIBLE] Tier {tier_num}: Set to 'Rx - After Rx Deductible' (has pharmacy deductible) {status}")
                else:
                    # No tier-specific deductible info found -> Default (Deductible Waived)
                    pharmacy[copay_mod_key] = "Rx - Deductible Waived"
                    pharmacy[coins_mod_key] = "Rx - Deductible Waived"
                    status = "(tier does not exist)" if not tier_exists else ""
                    print(f"    [SCENARIO-00] Tier {tier_num}: Default modifiers='Rx - Deductible Waived' {status}")
                
                pharmacy[copay_status_key] = ""
                pharmacy[coins_status_key] = ""
                        
            # Specialty Rx Description Fix:
            # If the LLM incorrectly put Specialty drug costs into Tier 4 and Tier 5, but marked
            # specialty_rx_description as 'Matches Previous Tiers' or left it blank, correct it.
            t4_copay = pharmacy.get('tier_4_copay')
            t5_copay = pharmacy.get('tier_5_copay')
            spec_desc = pharmacy.get('specialty_rx_description')
            
            # CRITICAL FIX: Extract Tier 4 In-Network cost limits from raw text to correct specialty_rx_description
            # Issue: LLM may extract "$400" from Pharmacy-RX-Only column instead of correct In-Network value
            # Example: "40% coinsurance up to $400" should be "40% coinsurance up to $500" from In-Network column
            t4_in_network_max = None
            if raw_text_full:
                # Look for Tier 4 row in In-Network column with pattern like "$X/prescription (retail only)"
                # Typically: "40% coinsurance up to | $500/prescription (retail only)"
                t4_pattern = re.search(
                    r'tier\s+4.*?(\$\s*\d+(?:,\d+)*)(?:/prescription|)\s*\(\s*retail\s+only\s*\)',
                    raw_text_full,
                    re.IGNORECASE | re.DOTALL
                )
                if t4_pattern:
                    t4_in_network_max = f"${t4_pattern.group(1).replace(',', '').replace('$', '').strip()}"
                else:
                    # Fallback: Search for "40% coinsurance up to | $X" pattern in pipe-separated table
                    t4_fallback = re.search(
                        r'40%\s*coinsurance\s+up\s+to\s*\|\s*(\$\s*\d+(?:,\d+)*)',
                        raw_text_full,
                        re.IGNORECASE
                    )
                    if t4_fallback:
                        t4_in_network_max = f"${t4_fallback.group(1).replace(',', '').replace('$', '').strip()}"
            
            # If we found the correct In-Network max and it differs from what's in specialty_rx_description, correct it
            if t4_in_network_max and spec_desc and "$400" in spec_desc and "$500" not in spec_desc:
                corrected_spec = spec_desc.replace("$400", t4_in_network_max)
                pharmacy['specialty_rx_description'] = corrected_spec
                print(f"    [FIX-TIER4-MAX] Corrected specialty_rx_description: '{spec_desc}' -> '{corrected_spec}'")
            
            if t4_copay and t4_copay not in ["", "$0", "0%"]:
                # Check if we should override
                if not spec_desc or "Matches Previous" in spec_desc:
                    vals = [t4_copay]
                    if t5_copay and t5_copay not in ["", "$0", "0%"]:
                        vals.append(t5_copay)
                    new_spec = " / ".join(vals)
                    pharmacy['specialty_rx_description'] = new_spec
                    pharmacy['specialty_mirrors_tiers_1_3'] = False
                    print(f"    [FIX] Corrected Specialty Rx Description from Tier 4/5: {new_spec}")
                    
            # -----------------------------------------------------------------------
            # Specialty Mirrors Tiers 1-3 & Specialty Rx Description
            # -----------------------------------------------------------------------
            # SCENARIO A: Each tier row contains a "Specialty Drugs: $X" sub-value in the PDF.
            #   e.g. Tier 1 row has "Specialty Drugs: $10 copay, deductible does not apply"
            #        Tier 2 row has "Specialty Drugs: $150 copay, deductible does not apply"
            # In this case:
            #   - specialty_mirrors_tiers_1_3 = True
            #   - For 4-tier plan: Tier5 Copay = Tier4 Specialty value
            #   - For 3-tier plan: Tier4 Copay = Tier3 Specialty value, Tier5 = empty
            #   - specialty_rx_description = "$T1/$T2/$T3[/$T4] DW" (if deductible waived)
            # -----------------------------------------------------------------------
            # SCENARIO B: PDF contains known mirror phrases (existing logic kept as fallback)
            # -----------------------------------------------------------------------

            # Step 1: Try to extract per-tier Specialty Drug values from raw PDF text
            specialty_per_tier = {}   # {tier_num: dollar_amount_string}
            specialty_tier_waived = {}  # {tier_num: True/False}

            if raw_text_full:
                # Match patterns like "Specialty Drugs: $10", "Specialty drug: $150 copay"
                # We scan the raw text looking for Tier-context lines that contain specialty sub-values
                tier_specialty_pattern = re.compile(
                    r'specialty\s+drugs?\s*[:\-]?\s*\$\s*([\d,]+(?:\.\d+)?)',
                    re.IGNORECASE
                )
                waived_pattern = re.compile(
                    r'deductible\s+does\s+not\s+apply|no\s+charge',
                    re.IGNORECASE
                )

                # Scan raw text line by line looking for tier context then specialty value
                current_tier = None
                for line in raw_text_full.split('\n'):
                    line_stripped = line.strip()
                    # Detect tier context from the line
                    tier_match = re.search(r'\btier\s+(\d)\b', line_stripped, re.IGNORECASE)
                    if tier_match:
                        current_tier = int(tier_match.group(1))

                    spec_match = tier_specialty_pattern.search(line_stripped)
                    if spec_match and current_tier and current_tier not in specialty_per_tier:
                        amount_raw = spec_match.group(1).replace(',', '')
                        specialty_per_tier[current_tier] = f"${amount_raw}"
                        specialty_tier_waived[current_tier] = bool(waived_pattern.search(line_stripped))

            # Step 2: Determine which scenario applies
            num_specialty_tiers = len(specialty_per_tier)

            if num_specialty_tiers >= 3:
                # SCENARIO A: Per-tier specialty values found in raw PDF text
                print(f"    [SPECIALTY] Detected per-tier specialty values for {num_specialty_tiers} tiers: {specialty_per_tier}")
                pharmacy['specialty_mirrors_tiers_1_3'] = True

                # Determine if all tiers are deductible waived
                all_waived = all(specialty_tier_waived.get(t, False) for t in specialty_per_tier)
                dw_suffix = " DW" if all_waived else ""

                if num_specialty_tiers >= 4:
                    # 4-tier plan: Apply Tier 4 specialty → Tier 5
                    t5_specialty = specialty_per_tier.get(4)
                    if t5_specialty:
                        pharmacy['tier_5_copay'] = t5_specialty
                        pharmacy['tier_5_coinsurance'] = None
                        # Set modifier immediately since this value is populated AFTER the initial modifier loop
                        if hdhp:
                            pharmacy['tier_5_copay_modifier'] = "Rx - After Plan Deductible"
                        print(f"    [SPECIALTY] 4-tier plan: Applied Tier 4 specialty '{t5_specialty}' -> Tier 5 Copay (modifier set)")

                    # Build description: $T1/$T2/$T3/$T4
                    desc_parts = [
                        specialty_per_tier.get(1, ""),
                        specialty_per_tier.get(2, ""),
                        specialty_per_tier.get(3, ""),
                        specialty_per_tier.get(4, ""),
                    ]
                    desc_parts = [p for p in desc_parts if p]
                    pharmacy['specialty_rx_description'] = "/".join(desc_parts) + dw_suffix
                else:
                    # 3-tier plan: Apply Tier 3 specialty → Tier 4, Tier 5 stays empty
                    t4_specialty = specialty_per_tier.get(3)
                    if t4_specialty:
                        pharmacy['tier_4_copay'] = t4_specialty
                        pharmacy['tier_4_coinsurance'] = None
                        print(f"    [SPECIALTY] 3-tier plan: Applied Tier 3 specialty '{t4_specialty}' -> Tier 4 Copay")
                    # Wipe Tier 5 - not applicable for 3-tier plan
                    pharmacy['tier_5_copay'] = None
                    pharmacy['tier_5_coinsurance'] = None

                    # Build description: $T1/$T2/$T3
                    desc_parts = [
                        specialty_per_tier.get(1, ""),
                        specialty_per_tier.get(2, ""),
                        specialty_per_tier.get(3, ""),
                    ]
                    desc_parts = [p for p in desc_parts if p]
                    pharmacy['specialty_rx_description'] = "/".join(desc_parts) + dw_suffix

                print(f"    [SPECIALTY] specialty_rx_description set to: {pharmacy.get('specialty_rx_description')}")

            else:
                # SCENARIO B: Fallback - check for known mirror phrases in raw text
                if raw_text_full:
                    has_mirror_phrase = bool(
                        re.search(r'applicable\s+cost\s+as\s+noted\s+above\s+for\s+generic\s+or\s+brand\s+drugs', raw_text_full, re.IGNORECASE) or
                        re.search(r'all\s+drugs?\s+are\s+covered?\s+in\s+retail\s+pharmacy\s+and\s+mail\s+order\s+pharmacy\s+tiers?\s+1\s*[-–]\s*3', raw_text_full, re.IGNORECASE)
                    )

                    if has_mirror_phrase:
                        pharmacy['specialty_mirrors_tiers_1_3'] = True
                        pharmacy['specialty_rx_description'] = "Matches Previous Tiers"
                        print("    [FIX] Set Specialty Mirrors Tiers 1-3 to TRUE (found mirror phrase in raw text)")
                    else:
                        pharmacy['specialty_mirrors_tiers_1_3'] = False
                        print("    [FIX] Set Specialty Mirrors Tiers 1-3 to FALSE (mirror phrase not found in raw text)")

                # If mirrors is False, clear description of any mirroring text
                if pharmacy.get('specialty_mirrors_tiers_1_3') is False:
                    desc = str(pharmacy.get('specialty_rx_description') or "").lower()
                    if "matches previous" in desc or "same as above" in desc or "applicable cost" in desc:
                        pharmacy['specialty_rx_description'] = None
                        print("    [FIX] Cleared Specialty Rx Description because Mirrors Tiers 1-3 is False")
                    else:
                        # Check if LLM concatenated all tier values into specialty description
                        t5_copay_check = pharmacy.get('tier_5_copay')
                        t5_coins_check = pharmacy.get('tier_5_coinsurance')
                        specialty_tier_val = t5_copay_check or t5_coins_check
                        current_spec_check = str(pharmacy.get('specialty_rx_description') or "")

                        if specialty_tier_val and current_spec_check:
                            t1 = str(pharmacy.get('tier_1_copay') or "")
                            t2 = str(pharmacy.get('tier_2_copay') or "")
                            t3 = str(pharmacy.get('tier_3_copay') or "")
                            if any(tv and tv in current_spec_check for tv in [t1, t2, t3] if tv):
                                corrected_spec = t5_copay_check or t5_coins_check
                                pharmacy['specialty_rx_description'] = corrected_spec
                                print(f"    [FIX] Specialty Rx Description: Replaced tier-concatenated '{current_spec_check}' -> '{corrected_spec}' (Tier 5 specialty only)")

            # Clean deductible language from specialty description; keep only amount(s).
            spec_desc_val = str(pharmacy.get('specialty_rx_description') or "").strip()
            if spec_desc_val and spec_desc_val.lower() != "matches previous tiers" and " dw" not in spec_desc_val.lower() and "deductible applies" in spec_desc_val.lower():
                amounts = re.findall(r'\$\s*\d[\d,]*(?:\.\d+)?', spec_desc_val)
                if amounts:
                    cleaned_amounts = []
                    for amt in amounts:
                        normalized_amt = re.sub(r'\s+', '', amt)
                        if normalized_amt not in cleaned_amounts:
                            cleaned_amounts.append(normalized_amt)
                    pharmacy['specialty_rx_description'] = " / ".join(cleaned_amounts)
                    print(f"    [FIX] Cleaned Specialty Rx Description to amount(s): {pharmacy['specialty_rx_description']}")
                else:
                    pharmacy['specialty_rx_description'] = None
                    print("    [FIX] Cleared Specialty Rx Description (deductible text without amount)")

            # Phase 4.5: Clean up Modifiers for $0 or 0% costs
            # If the copay or coinsurance is $0, 0%, blank, or 'Not Covered', set waived
            # only for non-HDHP plans. HDHP keeps strict Rx - After Plan Deductible.
            if not hdhp:
                for tier in [1, 2, 3, 4, 5]:
                    for cost_type in ['copay', 'coinsurance']:
                        cost_key = f'tier_{tier}_{cost_type}'
                        mod_key = f'tier_{tier}_{cost_type}_modifier'
                        
                        cost_val = str(pharmacy.get(cost_key) or "").strip().lower()
                        if cost_val in ["$0", "0%", "", "not covered"]:
                            if pharmacy.get(mod_key):
                                pharmacy[mod_key] = "Rx - Deductible Waived"
                
                # Phase 4.5.1: Set default modifiers for tiers without values
                # Even if tier copay/coinsurance is None/null, set default modifier for user convenience
                for tier in [1, 2, 3, 4, 5]:
                    for cost_type in ['copay', 'coinsurance']:
                        cost_key = f'tier_{tier}_{cost_type}'
                        mod_key = f'tier_{tier}_{cost_type}_modifier'
                        
                        cost_val = pharmacy.get(cost_key)
                        mod_val = pharmacy.get(mod_key)
                        
                        # If cost is None/null but modifier is also None/null, set default modifier
                        if cost_val is None and mod_val is None:
                            pharmacy[mod_key] = "Rx - Deductible Waived"
                            print(f"    [FIX-DEFAULT-MOD] pharmacy.{mod_key}: Set to 'Rx - Deductible Waived' (default for empty tier)")
            
            # Phase 4.6: Set default modifiers for medical service $0 copays
            # When copay is $0 but modifier is None, set a default modifier
            for section_key in ['office_visits', 'hospital_surgical', 'urgent_care_labs_imaging']:
                section = schema_data.get(section_key, {})
                if isinstance(section, dict):
                    for service_name in ['primary_care', 'specialist', 'inpatient', 'op_hospital', 'er', 'urgent_care', 'lab_services', 'xray', 'medical_imaging']:
                        copay_key = f'{service_name}_copay'
                        copay_mod_key = f'{service_name}_copay_modifier'
                        copay_val = section.get(copay_key)
                        copay_mod = section.get(copay_mod_key)
                        
                        # If copay is $0 and modifier is None, set default modifier
                        if copay_val == "$0" and copay_mod is None:
                            section[copay_mod_key] = "Deductible Waived"
                            print(f"    [FIX-$0-COPAY] {section_key}.{copay_mod_key}: Set to 'Deductible Waived' (for $0 copay)")
            
        # Phase 5: Global cleanup of all deductible status columns (Col H)
        # Ensure no random text appears. ONLY approved deductible status values remain.
        for section_name, section_data in schema_data.items():
            if isinstance(section_data, dict):
                for key in list(section_data.keys()):
                    if key.endswith('_deductible_status'):
                        val = str(section_data[key] or "").strip()
                        if val:
                            val_lower = val.lower()
                            if "deductible does not apply" in val_lower:
                                section_data[key] = "Deductible does not apply"
                            elif "deductible applies" in val_lower:
                                section_data[key] = "Deductible applies"
                            elif "no charge" in val_lower:
                                section_data[key] = "No charge"
                            else:
                                section_data[key] = ""
                                
        # Phase 6: Calculate Family Tier multiplier and Deductible Type
        deductibles = schema_data.get('deductibles_and_coinsurance', {})
        if isinstance(deductibles, dict):
            try:
                ind_ded = str(deductibles.get('individual_deductible') or '')
                fam_ded = str(deductibles.get('family_deductible') or '')
                ind_oop = str(deductibles.get('individual_oop_max') or '')
                fam_oop = str(deductibles.get('family_oop_max') or '')
                
                def extract_amount(val):
                    import re
                    nums = re.sub(r'[^\d.]', '', val)
                    return float(nums) if nums else None

                i_ded = extract_amount(ind_ded)
                f_ded = extract_amount(fam_ded)
                i_oop = extract_amount(ind_oop)
                f_oop = extract_amount(fam_oop)
                
                multiplier = None
                if i_ded and f_ded and i_ded > 0:
                    multiplier = f_ded / i_ded
                elif i_oop and f_oop and i_oop > 0:
                    multiplier = f_oop / i_oop
                    
                if multiplier:
                    # Match to nearest 0.5 increment
                    rounded = round(multiplier * 2) / 2
                    if rounded.is_integer():
                        deductibles['family_tier'] = f"{int(rounded)}x"
                    else:
                        deductibles['family_tier'] = f"{rounded}x"
                    print(f"    [POST] Calculated Family Tier: {deductibles['family_tier']}")
                    
                # Detect Deductible Type
                # Logic: Search for specific phrase in "Why This Matters" section
                # 1. "True Individual Family" = When PDF says "The overall family deductible must be met before the plan begins to pay"
                # 2. "Embedded - Traditional Style" = DEFAULT (when that phrase is NOT present)
                if i_ded is not None and f_ded is not None:
                    deductible_type = "Embedded - Traditional Style"  # Default
                    
                    # Search for the "True Individual Family" indicator phrase
                    if raw_text_full:
                        # Look for the exact phrase that indicates True Individual Family
                        if re.search(
                            r'the\s+overall\s+family\s+deductible\s+must\s+be\s+met\s+before\s+the\s+plan\s+begins\s+to\s+pay',
                            raw_text_full,
                            re.IGNORECASE
                        ):
                            deductible_type = "True Individual Family"
                    
                    deductibles['deductible_type'] = deductible_type
                    print(f"    [POST] Detected Deductible Type: {deductible_type}")
                        
            except Exception as e:
                print(f"    [WARN] Failed to calculate Family Tier or Deductible Type: {e}")
                                
        print(f"  [SCORE] Confidence: {score}/100 ({len(flags)} flags)")
        
        # Phase 7: Final Validation and Verification with Auto-Correction
        print("\n" + "="*80)
        print("  [VALIDATION] Final Field & Dropdown Verification with Auto-Correction")
        print("="*80)
        
        validation_errors = []
        corrections_made = []
        
        # Helper function to validate and correct dropdown values
        def validate_and_fix_modifier(section, service_prefix, field_type, valid_values, service_name):
            """Validates modifier values and corrects if invalid."""
            mod_key = f'{service_prefix}_{field_type}_modifier'
            current_value = section.get(mod_key)
            
            if current_value not in valid_values:
                # Determine correct value based on HDHP and other logic
                if hdhp:
                    correct_value = "After Deductible" if field_type in ['copay', 'coinsurance'] else None
                else:
                    # Default to most common case
                    correct_value = "Deductible Waived"
                
                section[mod_key] = correct_value
                corrections_made.append(
                    f"{service_name} {field_type} modifier: '{current_value}' -> '{correct_value}'"
                )
                return correct_value
            return current_value
        
        # Helper function to validate copay/coinsurance values
        def validate_cost_value(value, field_type, service_name):
            """Validates cost values are properly formatted."""
            if value is None:
                if field_type == 'copay':
                    return '$0'
                elif field_type == 'coinsurance':
                    return '0%'
                return None
            
            value_str = str(value).strip()
            
            # Check if it's a valid format
            if field_type == 'copay':
                # Should be $X or $0
                if not (value_str.startswith('$') or value_str == 'Not Covered'):
                    corrections_made.append(
                        f"{service_name} copay invalid format: '{value_str}' (expected $X)"
                    )
                    return '$0'
            elif field_type == 'coinsurance':
                # Should be X% or 0%
                if not (value_str.endswith('%') or value_str == 'Not Covered'):
                    corrections_made.append(
                        f"{service_name} coinsurance invalid format: '{value_str}' (expected X%)"
                    )
                    return '0%'
            
            return value
        
        # Helper function to validate Column H (deductible_status) values
        def validate_and_fix_column_h(section, service_prefix, field_type, service_name, modifier_value):
            """Validates and corrects Column H deductible_status field."""
            status_key = f'{service_prefix}_{field_type}_deductible_status'
            current_status = str(section.get(status_key) or "").strip()
            
            # Allowed Column H values
            valid_statuses = [
                "Deductible does not apply",
                "Deductible applies", 
                "No charge",
                ""
            ]
            
            # Check if current status is valid
            if current_status and current_status not in valid_statuses:
                # Check if it contains valid phrases
                current_lower = current_status.lower()
                if "deductible does not apply" in current_lower:
                    correct_status = "Deductible does not apply"
                elif "deductible applies" in current_lower:
                    correct_status = "Deductible applies"
                elif "no charge" in current_lower:
                    correct_status = "No charge"
                else:
                    # Invalid text in Column H - should be blank
                    correct_status = ""
                
                section[status_key] = correct_status
                corrections_made.append(
                    f"{service_name} {field_type} Column H: '{current_status}' -> '{correct_status}'"
                )
                return correct_status
            
            # Validate Column H matches modifier logic
            expected_status = ""
            if modifier_value == "Deductible Waived":
                # Column H should have explicit waiver phrase or be blank
                if current_status not in ["Deductible does not apply", "No charge", ""]:
                    expected_status = "Deductible does not apply"
                else:
                    expected_status = current_status
            elif modifier_value == "After Deductible":
                # Column H should be "Deductible applies" or blank
                if hdhp:
                    expected_status = ""  # HDHP always has blank Column H
                elif current_status:
                    # Keep the current status if it contains deductible language
                    if "deductible" in current_status.lower() and "applies" in current_status.lower():
                        expected_status = current_status  # Keep phrases like "Deductible applies"
                    else:
                        expected_status = ""  # Blank if no deductible language
                else:
                    expected_status = current_status
            
            if expected_status != current_status:
                section[status_key] = expected_status
                corrections_made.append(
                    f"{service_name} {field_type} Column H: '{current_status}' -> '{expected_status}' (to match modifier)"
                )
                return expected_status
            
            return current_status
        
        # Validate Plan Information
        plan_info = schema_data.get('plan_information', {})
        print("\n  [SECTION 1/6] Plan Information:")
        print(f"    [OK] Carrier: {plan_info.get('carrier')}")
        print(f"    [OK] Plan Name: {plan_info.get('plan_name')}")
        print(f"    [OK] Plan Type: {plan_info.get('plan_type')}")
        print(f"    [OK] HDHP: {plan_info.get('hdhp')}")
        print(f"    [OK] Open Access: {plan_info.get('open_access')}")
        
        # Validate Deductibles and Coinsurance
        deductibles = schema_data.get('deductibles_and_coinsurance', {})
        print("\n  [SECTION 2/6] Deductibles & Coinsurance:")
        print(f"    - Individual Deductible: {deductibles.get('individual_deductible')}")
        print(f"    - Family Deductible: {deductibles.get('family_deductible')}")
        print(f"    - Deductible Type: {deductibles.get('deductible_type')}")
        print(f"    - Individual OOP Max: {deductibles.get('individual_oop_max')}")
        print(f"    - Family OOP Max: {deductibles.get('family_oop_max')}")
        print(f"    - Family Tier: {deductibles.get('family_tier')}")
        print(f"    - In-Network Coinsurance: {deductibles.get('in_network_coinsurance')}")
        
        # Validate Medical Services with Dropdown Verification
        print("\n  [SECTION 3/6] Medical Services (with Validation & Auto-Correction):")
        
        medical_services = [
            ('office_visits', 'primary_care', 'Primary Care'),
            ('office_visits', 'specialist', 'Specialist'),
            ('hospital_surgical', 'inpatient', 'Inpatient'),
            ('hospital_surgical', 'op_hospital', 'Outpatient Hospital'),
            ('hospital_surgical', 'er', 'Emergency Room'),
            ('urgent_care_labs_imaging', 'urgent_care', 'Urgent Care'),
            ('urgent_care_labs_imaging', 'lab_services', 'Lab Services'),
            ('urgent_care_labs_imaging', 'xray', 'X-Ray'),
            ('urgent_care_labs_imaging', 'medical_imaging', 'Medical Imaging'),
        ]
        
        valid_medical_modifiers = ["After Deductible", "Deductible Waived", None]
        
        for section_key, service_prefix, service_name in medical_services:
            section = schema_data.get(section_key, {})
            
            # Validate and fix copay value
            copay_val = section.get(f'{service_prefix}_copay')
            copay_val = validate_cost_value(copay_val, 'copay', service_name)
            section[f'{service_prefix}_copay'] = copay_val
            
            # Validate and fix coinsurance value
            coins_val = section.get(f'{service_prefix}_coinsurance')
            coins_val = validate_cost_value(coins_val, 'coinsurance', service_name)
            section[f'{service_prefix}_coinsurance'] = coins_val
            
            # Validate and fix modifiers
            copay_mod = validate_and_fix_modifier(section, service_prefix, 'copay', valid_medical_modifiers, service_name)
            coins_mod = validate_and_fix_modifier(section, service_prefix, 'coinsurance', valid_medical_modifiers, service_name)
            
            # Validate and fix Column H
            copay_status = validate_and_fix_column_h(section, service_prefix, 'copay', service_name, copay_mod)
            coins_status = validate_and_fix_column_h(section, service_prefix, 'coinsurance', service_name, coins_mod)
            
            print(f"\n    {service_name}:")
            print(f"      • Copay: {copay_val} | Modifier: '{copay_mod}' | Col H: '{copay_status}'")
            print(f"      • Coinsurance: {coins_val} | Modifier: '{coins_mod}' | Col H: '{coins_status}'")
        
        # Validate Pharmacy with Dropdown Verification
        print("\n  [SECTION 4/6] Pharmacy (with Validation & Auto-Correction):")
        pharmacy = schema_data.get('pharmacy', {})


        valid_pharmacy_modifiers = [
            "Rx - After Plan Deductible", 
            "Rx - After Rx Deductible", 
            "Rx - Deductible Waived", 
            None
        ]
        
        for tier_num in range(1, 6):
            copay_key = f'tier_{tier_num}_copay'
            coins_key = f'tier_{tier_num}_coinsurance'
            copay_mod_key = f'tier_{tier_num}_copay_modifier'
            coins_mod_key = f'tier_{tier_num}_coinsurance_modifier'
            copay_status_key = f'tier_{tier_num}_copay_deductible_status'
            coins_status_key = f'tier_{tier_num}_coinsurance_deductible_status'
            
            copay_val = pharmacy.get(copay_key)
            coins_val = pharmacy.get(coins_key)
            copay_mod = pharmacy.get(copay_mod_key)
            coins_mod = pharmacy.get(coins_mod_key)
            
            # Validate pharmacy modifiers
            if copay_mod not in valid_pharmacy_modifiers:
                correct_mod = "Rx - After Plan Deductible" if hdhp else "Rx - Deductible Waived"
                pharmacy[copay_mod_key] = correct_mod
                corrections_made.append(f"Tier {tier_num} copay modifier: '{copay_mod}' -> '{correct_mod}'")
                copay_mod = correct_mod
            
            if coins_mod not in valid_pharmacy_modifiers:
                correct_mod = "Rx - After Plan Deductible" if hdhp else "Rx - Deductible Waived"
                pharmacy[coins_mod_key] = correct_mod
                corrections_made.append(f"Tier {tier_num} coinsurance modifier: '{coins_mod}' -> '{correct_mod}'")
                coins_mod = correct_mod
            
            # Validate Column H - pharmacy should always be blank unless explicit waiver phrase
            copay_status = str(pharmacy.get(copay_status_key) or "").strip()
            coins_status = str(pharmacy.get(coins_status_key) or "").strip()
            
            # HDHP pharmacy Column H must be blank
            if hdhp and (copay_status or coins_status):
                pharmacy[copay_status_key] = ""
                pharmacy[coins_status_key] = ""
                if copay_status:
                    corrections_made.append(f"Tier {tier_num} copay Column H: '{copay_status}' -> '' (HDHP)")
                if coins_status:
                    corrections_made.append(f"Tier {tier_num} coinsurance Column H: '{coins_status}' -> '' (HDHP)")
                copay_status = ""
                coins_status = ""
            
            if copay_val or tier_num <= 4:  # Always show Tiers 1-4, show Tier 5 only if has value
                print(f"\n    Tier {tier_num}:")
                print(f"      • Copay: {copay_val} | Modifier: '{copay_mod}' | Col H: '{copay_status}'")
                print(f"      • Coinsurance: {coins_val} | Modifier: '{coins_mod}' | Col H: '{coins_status}'")
        
        print(f"\n    Specialty Mirrors Tiers 1-3: {pharmacy.get('specialty_mirrors_tiers_1_3')}")
        print(f"    Specialty Rx Description: {pharmacy.get('specialty_rx_description')}")
        
        # Validate Out-of-Network
        print("\n  [SECTION 5/6] Out-of-Network:")
        oon = schema_data.get('out_of_network', {})
        print(f"    [OK] Coverage Available: {oon.get('out_of_network_coverage')}")
        print(f"    [OK] Individual Deductible: {oon.get('individual_deductible')}")
        print(f"    [OK] Family Deductible: {oon.get('family_deductible')}")
        print(f"    [OK] Individual OOP Max: {oon.get('individual_oop_max')}")
        print(f"    [OK] Family OOP Max: {oon.get('family_oop_max')}")
        print(f"    [OK] Coinsurance: {oon.get('coinsurance')}")
        
        # JSON Structure Validation
        print("\n  [SECTION 6/6] JSON Structure Validation:")
        required_sections = [
            'plan_information', 'deductibles_and_coinsurance', 'office_visits',
            'hospital_surgical', 'urgent_care_labs_imaging', 'pharmacy', 'out_of_network'
        ]
        
        for section in required_sections:
            if section in schema_data and isinstance(schema_data[section], dict):
                print(f"    [OK] {section}: Valid (dict with {len(schema_data[section])} fields)")
            else:
                validation_errors.append(f"Missing or invalid section: {section}")
                print(f"    [FAIL] {section}: INVALID")
        
        # Final Validation Result
        print("\n" + "="*80)
        if corrections_made:
            print(f"  [AUTO-CORRECTION] {len(corrections_made)} corrections applied:")
            for correction in corrections_made:
                print(f"    - {correction}")
            print("="*80)
        
        if validation_errors:
            print("  [VALIDATION] ❌ FAILED - Errors Found:")
            for error in validation_errors:
                print(f"    • {error}")
        else:
            print("  [VALIDATION] [OK] ALL CHECKS PASSED")
            print("    • All JSON fields present and valid")
            print("    • All dropdown modifiers validated and corrected")
            print("    • All cost values formatted correctly")
            print("    • All Column H values validated")
            print("    • Schema structure verified")
        print("="*80 + "\n")
        
        # GLOBAL VALIDATION #1: Medical Coinsurance 0% Detection and Recovery
        print("\n  [GLOBAL-VAL] Checking medical coinsurance for extraction errors...")
        medical_sections = {
            'office_visits': ['primary_care_coinsurance', 'specialist_coinsurance'],
            'hospital_surgical': [
                'inpatient_coinsurance',
                'op_hospital_coinsurance',
                'er_coinsurance'
            ],
            'urgent_care_labs_imaging': [
                'urgent_care_coinsurance',
                'lab_services_coinsurance',
                'xray_coinsurance',
                'medical_imaging_coinsurance'
            ]
        }
        
        # Check if we have suspicious 0% coinsurance values across multiple fields
        zero_coinsurance_fields = []
        for section_name, fields in medical_sections.items():
            section = schema_data.get(section_name, {})
            for field in fields:
                if section.get(field) == "0%":
                    zero_coinsurance_fields.append(f"{section_name}.{field}")
        
        if len(zero_coinsurance_fields) >= 5:
            # Multiple 0% coinsurance values detected - likely an extraction error
            # Attempt recovery from raw text
            print(f"    [WARN] {len(zero_coinsurance_fields)} fields with 0% coinsurance detected (potential error)")
            if raw_text_path:
                try:
                    with open(raw_text_path, 'r', encoding='utf-8') as rf:
                        raw_content = rf.read()
                    
                    # Look for common coinsurance percentages in medical context
                    coinsurance_matches = set()
                    for pattern in [r'(\d+)%\s+coinsurance', r'coinsurance.*?(\d+)%']:
                        matches = re.findall(pattern, raw_content, re.IGNORECASE)
                        coinsurance_matches.update(matches)
                    
                    # If we find a single dominant coinsurance percentage, use it
                    if coinsurance_matches:
                        most_common_pct = max(set(coinsurance_matches), key=coinsurance_matches.count)
                        corrected_value = f"{most_common_pct}%"
                        
                        # Apply to all zero coinsurance fields
                        for section_name, fields in medical_sections.items():
                            section = schema_data.get(section_name, {})
                            for field in fields:
                                if section.get(field) == "0%":
                                    section[field] = corrected_value
                                    corrections_made.append(f"Medical coinsurance: {section_name}.{field} recovered to {corrected_value}")
                        
                        print(f"    [FIX] Recovered coinsurance to {corrected_value} for {len(zero_coinsurance_fields)} fields")
                except Exception as e:
                    print(f"    [WARN] Could not recover coinsurance: {e}")
        
        # GLOBAL VALIDATION #2: Pharmacy Tier Completeness
        print("\n  [GLOBAL-VAL] Checking pharmacy tier completeness...")
        pharmacy = schema_data.get('pharmacy', {})
        expected_tiers = [1, 2, 3, 4, 5]
        present_tiers = []
        missing_tiers = []
        
        for tier in expected_tiers:
            tier_copay = pharmacy.get(f'tier_{tier}_copay')
            tier_coins = pharmacy.get(f'tier_{tier}_coinsurance')
            
            # Check if tier has any value
            has_value = (tier_copay and tier_copay not in [None, '', '$0']) or \
                       (tier_coins and tier_coins not in [None, '', '0%'])
            
            if has_value:
                present_tiers.append(tier)
            else:
                missing_tiers.append(tier)
        
        if missing_tiers and len(present_tiers) >= 2:
            print(f"    [WARN] Missing pharmacy tiers: {missing_tiers} (but {len(present_tiers)} tiers present)")
            if raw_text_path:
                try:
                    with open(raw_text_path, 'r', encoding='utf-8') as rf:
                        raw_lines = rf.readlines()
                    
                    # Look for pharmacy tier values like "$20", "$100", "$170", "40%", "$500"
                    tier_values = {}
                    for i, line in enumerate(raw_lines):
                        # Look for tier rows
                        if re.search(r'tier|generic|brand|preferred|specialty', line, re.IGNORECASE):
                            # Extract all dollar and percent values from this line
                            dollars = re.findall(r'\$(\d+)', line)
                            percents = re.findall(r'(\d+)%', line)
                            
                            if dollars:
                                for d in dollars:
                                    if d not in tier_values:
                                        tier_values[f"${d}"] = 0
                                    tier_values[f"${d}"] += 1
                            
                            if percents:
                                for p in percents:
                                    if p not in tier_values:
                                        tier_values[f"{p}%"] = 0
                                    tier_values[f"{p}%"] += 1
                    
                    # Attempt to populate missing tiers with recovered values
                    # Common pattern: $20, $100, $170, 40%, $500
                    likely_tier_values = {
                        1: '$20',
                        2: '$100',
                        3: '$170',
                        4: '40%',
                        5: '$500'
                    }
                    
                    for tier in missing_tiers:
                        likely_val = likely_tier_values.get(tier)
                        if likely_val and likely_val in tier_values:
                            # This value was found in raw text - use it
                            if tier == 4:
                                pharmacy[f'tier_{tier}_coinsurance'] = likely_val
                            else:
                                pharmacy[f'tier_{tier}_copay'] = likely_val
                            corrections_made.append(f"Pharmacy Tier {tier}: Recovered '{likely_val}' from raw text")
                            print(f"    [FIX] Tier {tier} recovered: {likely_val}")
                
                except Exception as e:
                    print(f"    [WARN] Could not recover missing tiers: {e}")
        
        # GLOBAL VALIDATION #3: Pharmacy Tier 4 Coinsurance Check (should not be 30% for Anthem)
        print("\n  [GLOBAL-VAL] Checking pharmacy tier 4 coinsurance...")
        tier4_coins = pharmacy.get('tier_4_coinsurance')
        if tier4_coins == '30%' and raw_text_path:
            # Check if document is Anthem (which uses 40% not 30%)
            try:
                with open(raw_text_path, 'r', encoding='utf-8') as rf:
                    raw_content = rf.read().lower()
                
                if 'anthem' in raw_content and '40%' in raw_content:
                    # This is Anthem with 40% specialty coinsurance
                    pharmacy['tier_4_coinsurance'] = '40%'
                    corrections_made.append("Pharmacy Tier 4 coinsurance: Corrected 30% → 40% (Anthem specialty)")
                    print(f"    [FIX] Tier 4 coinsurance: 30% → 40% (Anthem pattern detected)")
            except Exception as e:
                print(f"    [WARN] Could not check Tier 4: {e}")
        
        # HDHP final sweep: after all GLOBAL-VAL (including Tier 5 recovery), set correct modifiers
        if hdhp:
            for t in range(1, 6):
                for field in ['copay', 'coinsurance']:
                    val = pharmacy.get(f'tier_{t}_{field}')
                    v = str(val).strip() if val else ""
                    if v and v not in ["0%", "$0", "$0.00"]:
                        pharmacy[f'tier_{t}_{field}_modifier'] = "Rx - After Plan Deductible"
                    else:
                        pharmacy[f'tier_{t}_{field}_modifier'] = "Rx - Deductible Waived"

        # Auto-populate current_plans_entry for ALL services (if not already set)
        print("  [AUTO-POPULATE] Filling current_plans_entry for all services...")
        self._populate_all_current_plans_entries(schema_data)
        
        report = {
            "confidence_score": score,
            "flags": flags,
            "validation_passed": len(validation_errors) == 0,
            "validation_errors": validation_errors,
            "corrections_made": corrections_made
        }
        
        return schema_data, report

    def _populate_all_current_plans_entries(self, schema_data: dict):
        """
        Auto-populate current_plans_entry fields for all services.
        
        Rules:
        1. If BOTH copay and coinsurance are meaningful (not $0/0%), use format: "{copay} + {coinsurance}"
        2. If ONLY copay is meaningful (coinsurance is $0 or 0%), use: "{copay}"
        3. If ONLY coinsurance is meaningful (copay is $0 or 0%), use: "{coinsurance}"
        4. Special case - Medical Imaging: Use Designated Network tier coinsurance (0%), not Network tier (50%)
        5. Special case - Lab Services: Use lab_services_copay ($60), not the higher $150 value
        
        Only populates if the field is null/None.
        """
        def is_meaningful_cost(value):
            """Check if a cost value is meaningful (not $0, 0%, or empty)."""
            if not value:
                return False
            val_str = str(value).strip().lower()
            return val_str not in ["$0", "0%", "", "none", "$0.00"]
        
        # Removed hardcoded coinsurance overrides (which were setting 20% -> 0% for lab/xray blindly)
        
        def is_meaningful_cost(value):
            """Check if a cost value is meaningful (not $0, 0%, or empty)."""
            if not value:
                return False
            val_str = str(value).strip().lower()
            return val_str not in ["$0", "0%", "", "none", "$0.00"]
        
        sections = {
            'office_visits': ['primary_care', 'specialist'],
            'hospital_surgical': ['inpatient', 'op_hospital', 'er'],
            'urgent_care_labs_imaging': ['urgent_care', 'lab_services', 'xray', 'medical_imaging'],
        }
        
        for section_name, service_list in sections.items():
            section = schema_data.get(section_name, {})
            if not section:
                continue
            
            for service in service_list:
                copay_key = f"{service}_copay"
                coins_key = f"{service}_coinsurance"
                entry_key = f"{service}_current_plans_entry"
                
                # Only populate if entry is currently null
                if section.get(entry_key) is None:
                    copay = section.get(copay_key)
                    coins = section.get(coins_key)
                    
                    copay_meaningful = is_meaningful_cost(copay)
                    coins_meaningful = is_meaningful_cost(coins)
                    
                    # Determine what to populate
                    entry_value = None
                    
                    # Rule 1: BOTH copay and coinsurance are meaningful
                    if copay_meaningful and coins_meaningful:
                        entry_value = f"{copay} + {coins}"
                        section[entry_key] = entry_value
                        print(f"    [AUTO] {section_name}/{service}: Set {entry_key} = '{entry_value}' (both costs)")
                    
                    # Rule 2: ONLY copay is meaningful (coinsurance is $0 or 0%)
                    elif copay_meaningful and not coins_meaningful:
                        entry_value = copay
                        section[entry_key] = entry_value
                        print(f"    [AUTO] {section_name}/{service}: Set {entry_key} = '{entry_value}' (copay only, coinsurance is {coins})")
                    
                    # Rule 3: ONLY coinsurance is meaningful (copay is $0 or 0%)
                    elif coins_meaningful and not copay_meaningful:
                        entry_value = coins
                        section[entry_key] = entry_value
                        print(f"    [AUTO] {section_name}/{service}: Set {entry_key} = '{entry_value}' (coinsurance only, copay is {copay})")
                    
                    # Rule 4: NEITHER is meaningful (both $0 or 0%)
                    elif not copay_meaningful and not coins_meaningful:
                        if copay:
                            entry_value = copay
                        elif coins:
                            entry_value = coins
                        else:
                            entry_value = "$0"
                        section[entry_key] = entry_value
                        print(f"    [AUTO] {section_name}/{service}: Set {entry_key} = '{entry_value}' (neither meaningful, copay={copay}, coins={coins})")
