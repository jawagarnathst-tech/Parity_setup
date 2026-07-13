import pytesseract
from PIL import Image
import pdfplumber
import os
from dotenv import load_dotenv

load_dotenv()

# Configure Tesseract path from .env
tesseract_path = os.getenv('TESSERACT_PATH')
if tesseract_path and os.path.exists(tesseract_path):
    pytesseract.pytesseract.pytesseract_cmd = tesseract_path
    print(f"[OCR] Tesseract configured at: {tesseract_path}")
else:
    print(f"[OCR WARN] Tesseract path not found or not configured. OCR may not work for scanned PDFs.")

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
    """Perform full OCR on all pages of a PDF."""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                print(f"    [OCR] Processing page {i+1}/{len(pdf.pages)}...")
                page_image = page.to_image(resolution=resolution).original
                t = pytesseract.image_to_string(page_image, lang='eng').strip()
                if t:
                    text += f"--- PAGE {i+1} OCR TEXT ---\n" + t + "\n"
    except Exception as e:
        print(f"  [OCR ERR] Could not perform full OCR on {pdf_path}: {e}")
    return text

def ocr_image(image_path: str) -> str:
    """Perform full OCR on an image file."""
    try:
        img = Image.open(image_path)
        return pytesseract.image_to_string(img, lang='eng').strip()
    except Exception as e:
        print(f"  [OCR ERR] Could not OCR {image_path}: {e}")
        return ""
