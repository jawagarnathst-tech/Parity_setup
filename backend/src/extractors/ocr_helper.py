
import pytesseract
from PIL import Image
import pdfplumber
import fitz  # PyMuPDF
import os
import io
import re
import tempfile
import uuid
from dotenv import load_dotenv

load_dotenv()

# Configure Tesseract path from .env
tesseract_path = os.getenv('TESSERACT_PATH')
if tesseract_path and os.path.exists(tesseract_path):
    pytesseract.pytesseract.pytesseract_cmd = tesseract_path
    print(f"[OCR] Tesseract configured at: {tesseract_path}")
else:
    print(f"[OCR WARN] Tesseract path not found or not configured. OCR may not work for scanned PDFs.")

# SBC-specific keywords for orientation scoring
_SBC_KEYWORDS = {
    'summary', 'benefits', 'coverage', 'covers', 'plan', 'deductible',
    'copay', 'copayment', 'coinsurance', 'network', 'out-of-pocket',
    'emergency', 'prescription', 'services', 'care', 'hospital',
    'limit', 'tier', 'specialist', 'physician', 'waived',
    'pharmacy', 'inpatient', 'outpatient', 'urgent',
}

# PIL transpose constants for clockwise rotation
_CW_TRANSPOSE = {
    90:  Image.ROTATE_270,
    180: Image.ROTATE_180,
    270: Image.ROTATE_90,
}


def _score_image_orientation(img: Image.Image) -> int:
    """
    Score all four 90° rotations by counting SBC keyword hits in the top 45% of
    the page image.  Returns the best clockwise rotation angle (0, 90, 180, 270).
    Uses Tesseract OSD as a fast first-guess to avoid testing all four angles.
    """
    w, h = img.size

    def _kw_score(candidate_img: Image.Image) -> int:
        cw, ch = candidate_img.size
        sample = candidate_img.crop((0, 0, cw, int(ch * 0.45)))
        txt = pytesseract.image_to_string(sample, lang='eng').lower()
        return sum(1 for kw in _SBC_KEYWORDS if kw in txt)

    # Quick check: is the page already upright?
    score_0 = _kw_score(img)
    if score_0 >= 5:
        return 0

    # Ask Tesseract OSD for a fast hint
    candidate_angles = [90, 180, 270]
    try:
        osd = pytesseract.image_to_osd(img)
        for line in osd.splitlines():
            if line.startswith('Rotate:'):
                osd_angle = int(line.split(':')[1].strip())
                if osd_angle in (90, 180, 270):
                    # Move OSD suggestion to front
                    candidate_angles.remove(osd_angle)
                    candidate_angles.insert(0, osd_angle)
    except Exception:
        pass  # OSD can fail on low-content pages — continue anyway

    best_angle = 0
    best_score = score_0

    for angle in candidate_angles:
        rotated = img.transpose(_CW_TRANSPOSE[angle])
        score = _kw_score(rotated)
        if score > best_score:
            best_score = score
            best_angle = angle
        if score >= 5:
            # Strong SBC match — no need to test remaining angles
            break

    return best_angle


def detect_pdf_rotation(pdf_path: str) -> int:
    """
    Inspect the first page of a PDF (using PyMuPDF) and return the clockwise
    rotation angle (0, 90, 180, 270) needed to make it upright for OCR.
    Returns 0 if the page is already correctly oriented.
    """
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        pix = page.get_pixmap(dpi=150)
        img = Image.open(io.BytesIO(pix.tobytes('png')))
        doc.close()
        return _score_image_orientation(img)
    except Exception as e:
        print(f"  [OCR WARN] Could not detect PDF orientation: {e}")
        return 0


def _create_rotated_pdf(pdf_path: str, rotation: int) -> str:
    """
    Write a corrected copy of *pdf_path* with all pages rotated by *rotation*
    degrees (clockwise) into a temp file. Returns the temp file path.
    Caller is responsible for deleting the file when done.
    """
    doc = fitz.open(pdf_path)
    for page in doc:
        current = page.rotation
        page.set_rotation((current + rotation) % 360)
    tmp = tempfile.NamedTemporaryFile(
        suffix='.pdf',
        dir=os.path.dirname(pdf_path),
        delete=False,
        prefix='_rot_'
    )
    tmp_path = tmp.name
    tmp.close()
    doc.save(tmp_path)
    doc.close()
    return tmp_path


def ocr_pdf_header(pdf_path: str, page_number: int = 0, header_height_ratio: float = 0.25, resolution: int = 300) -> str:
    """OCR the top header area of the given PDF page and return extracted text."""
    with pdfplumber.open(pdf_path) as pdf:
        if page_number >= len(pdf.pages):
            return ""
        page = pdf.pages[page_number]
        page_image = page.to_image(resolution=resolution).original
        width, height = page_image.size
        crop_height = max(1, int(height * header_height_ratio))
        header_image = page_image.crop((0, 0, width, crop_height))
        return pytesseract.image_to_string(header_image, lang='eng').strip()


def ocr_pdf_full(pdf_path: str, resolution: int = 300) -> str:
    """
    Perform full OCR on all pages of a PDF.

    Pipeline:
      1. Auto-detect page orientation and correct if needed.
      2. Try rostaing-ocr (layout-aware deep-learning OCR).
      3. Validate result — skip bare '--- Page X ---' headers as empty.
      4. Fall back to pytesseract if rostaing-ocr yields too little real text.
    """

    # ── Step 1: Auto-orientation ──────────────────────────────────────────────
    rotation_needed = detect_pdf_rotation(pdf_path)
    rotated_pdf_path = None  # path to temp corrected PDF (if any)

    if rotation_needed != 0:
        print(f"  [ORIENT] Detected {rotation_needed}° CW rotation. Auto-correcting before OCR...")
        try:
            rotated_pdf_path = _create_rotated_pdf(pdf_path, rotation_needed)
            ocr_target = rotated_pdf_path
            print(f"  [ORIENT] Rotated PDF created: {os.path.basename(rotated_pdf_path)}")
        except Exception as e:
            print(f"  [ORIENT WARN] Could not create rotated PDF: {e}. Proceeding with original.")
            ocr_target = pdf_path
    else:
        ocr_target = pdf_path

    def _meaningful_chars(text: str) -> int:
        """Count alnum characters after stripping page-separator headers."""
        cleaned = re.sub(r'---\s*Page\s*\d+\s*---', '', text, flags=re.IGNORECASE)
        return len(re.findall(r'[a-zA-Z0-9]', cleaned))

    text = ""

    try:
        # ── Step 2: Try rostaing-ocr ──────────────────────────────────────────────
        try:
            print(f"    [OCR] Attempting layout-aware extraction with rostaing-ocr...")
            from rostaing_ocr import ocr_extractor

            temp_dir = os.path.dirname(pdf_path)
            temp_filename = f"temp_rostaing_{uuid.uuid4().hex}.txt"
            temp_out = os.path.join(temp_dir, temp_filename)

            ocr_extractor(ocr_target, output_file=temp_out)

            if os.path.exists(temp_out):
                with open(temp_out, "r", encoding="utf-8") as f:
                    text = f.read()
                try:
                    os.remove(temp_out)
                except Exception as e_del:
                    print(f"    [OCR WARN] Could not delete temp file {temp_out}: {e_del}")

            # ── Step 3: Validate rostaing-ocr result ─────────────────────────────
            if _meaningful_chars(text) > 150:
                print(f"    [OCR] Successfully extracted text using rostaing-ocr "
                      f"({_meaningful_chars(text)} meaningful chars)")
                return text
            else:
                print(f"    [OCR WARN] rostaing-ocr returned insufficient text "
                      f"({_meaningful_chars(text)} meaningful chars). Falling back to pytesseract.")

        except Exception as e:
            print(f"    [OCR WARN] rostaing-ocr failed or is not available: {e}. Falling back to pytesseract.")

        # ── Step 4: Pytesseract fallback ─────────────────────────────────────────
        text = ""
        try:
            print(f"    [OCR] Processing with pytesseract...")
            doc = fitz.open(ocr_target)
            for i, page in enumerate(doc):
                print(f"    [OCR] Processing page {i+1}/{len(doc)}...")
                pix = page.get_pixmap(dpi=resolution)
                img = Image.open(io.BytesIO(pix.tobytes('png')))
                t = pytesseract.image_to_string(img, lang='eng').strip()
                if t:
                    text += f"--- PAGE {i+1} OCR TEXT ---\n" + t + "\n"
            doc.close()
        except Exception as e:
            print(f"  [OCR ERR] Could not perform full OCR on {pdf_path}: {e}")

        return text
    finally:
        # ── Cleanup temp rotated PDF ──────────────────────────────────────────
        if rotated_pdf_path and os.path.exists(rotated_pdf_path):
            try:
                os.remove(rotated_pdf_path)
                print(f"  [ORIENT] Cleaned up temporary rotated PDF: {os.path.basename(rotated_pdf_path)}")
            except Exception as e_cleanup:
                print(f"  [ORIENT WARN] Could not delete temp rotated PDF: {e_cleanup}")


def ocr_image(image_path: str) -> str:
    """Perform full OCR on an image file."""
    try:
        img = Image.open(image_path)
        return pytesseract.image_to_string(img, lang='eng').strip()
    except Exception as e:
        print(f"  [OCR ERR] Could not OCR {image_path}: {e}")
        return ""
