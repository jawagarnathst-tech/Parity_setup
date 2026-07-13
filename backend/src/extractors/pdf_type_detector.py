"""
PDF Type Detection Module
Detects whether a PDF is Digital, Fully Scanned, or Mixed (hybrid)
"""
import pdfplumber
import os


class PDFTypeDetector:
    """Analyzes PDF to determine if it's digital, scanned, or mixed."""
    
    def __init__(self, extraction_threshold: float = 0.7, scanned_threshold: float = 0.3):
        """
        Initialize detector with thresholds.
        
        Args:
            extraction_threshold: Ratio above which a page is considered digital (0-1)
            scanned_threshold: Ratio below which a page is considered scanned (0-1)
        """
        self.extraction_threshold = extraction_threshold
        self.scanned_threshold = scanned_threshold
    
    def _analyze_page(self, page) -> dict:
        """
        Analyze a single page to determine if it's digital or scanned.
        
        Returns:
            dict with keys:
            - 'type': 'digital', 'scanned', or 'unclear'
            - 'text_content': extracted text
            - 'meaningful_chars': count of meaningful characters
            - 'total_chars': total extracted characters
            - 'extraction_ratio': meaningful_chars / (total_chars + 1)
        """
        # Extract text
        text = page.extract_text() or ""
        
        # Extract tables
        tables = page.extract_tables() or []
        table_text = ""
        if tables:
            for table in tables:
                for row in table:
                    clean_row = [
                        str(cell).replace('\n', ' ').strip() 
                        for cell in row if cell
                    ]
                    table_text += " | ".join(clean_row) + "\n"
        
        # Combine all extracted content
        total_content = text + "\n" + table_text
        
        # Count meaningful characters (remove pipes, spaces, newlines, dashes)
        meaningful = total_content.replace('|', '').replace('-', '').replace('=', '').strip()
        meaningful_chars = len(meaningful)
        total_chars = len(total_content)
        
        # Calculate extraction ratio
        extraction_ratio = meaningful_chars / (total_chars + 1) if total_chars > 0 else 0
        
        # Determine page type
        if meaningful_chars < 50:
            # Very little meaningful content - likely scanned
            page_type = "scanned"
        elif extraction_ratio >= self.extraction_threshold:
            # High extraction ratio - likely digital
            page_type = "digital"
        elif extraction_ratio <= self.scanned_threshold:
            # Low extraction ratio - likely scanned
            page_type = "scanned"
        else:
            # In between - mixed or unclear
            page_type = "unclear"
        
        return {
            "type": page_type,
            "text_content": total_content,
            "meaningful_chars": meaningful_chars,
            "total_chars": total_chars,
            "extraction_ratio": extraction_ratio
        }
    
    def detect_pdf_type(self, pdf_path: str) -> dict:
        """
        Detect the type of PDF (digital, scanned, or mixed).
        
        Returns:
            dict with keys:
            - 'pdf_type': 'digital', 'scanned', or 'mixed'
            - 'page_types': list of page type dicts with detailed info
            - 'digital_pages': list of page indices that are digital
            - 'scanned_pages': list of page indices that are scanned
            - 'mixed_pages': list of page indices that are unclear/mixed
            - 'summary': human-readable summary string
        """
        page_types = []
        digital_pages = []
        scanned_pages = []
        mixed_pages = []
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                
                for page_idx, page in enumerate(pdf.pages):
                    analysis = self._analyze_page(page)
                    page_types.append({
                        "page_num": page_idx + 1,
                        **analysis
                    })
                    
                    if analysis["type"] == "digital":
                        digital_pages.append(page_idx)
                    elif analysis["type"] == "scanned":
                        scanned_pages.append(page_idx)
                    else:
                        mixed_pages.append(page_idx)
                
                # Determine overall PDF type
                if len(scanned_pages) == 0:
                    pdf_type = "digital"
                    summary = f"Digital PDF: All {total_pages} pages are digital (searchable text)"
                elif len(digital_pages) == 0:
                    pdf_type = "scanned"
                    summary = f"Fully Scanned PDF: All {total_pages} pages are scanned (image-based)"
                else:
                    pdf_type = "mixed"
                    summary = f"Mixed PDF: {len(digital_pages)} digital page(s), {len(scanned_pages)} scanned page(s), {len(mixed_pages)} unclear page(s)"
                
                return {
                    "pdf_type": pdf_type,
                    "page_types": page_types,
                    "digital_pages": digital_pages,
                    "scanned_pages": scanned_pages,
                    "mixed_pages": mixed_pages,
                    "summary": summary,
                    "total_pages": total_pages
                }
        
        except Exception as e:
            print(f"  [ERROR] Could not analyze PDF: {e}")
            return {
                "pdf_type": "unknown",
                "page_types": [],
                "digital_pages": [],
                "scanned_pages": [],
                "mixed_pages": [],
                "summary": f"Error analyzing PDF: {e}",
                "total_pages": 0
            }
