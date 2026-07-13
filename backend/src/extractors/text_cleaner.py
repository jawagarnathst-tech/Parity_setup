import re

class TextCleaner:
    """
    Cleans raw PDF-extracted text before sending to AI.
    Removes noise such as page numbers, boilerplate headers/footers,
    encoding artifacts, and excessive whitespace.
    """

    # Common SBC boilerplate phrases that appear repeatedly across pages
    BOILERPLATE_PATTERNS = [
        r'Page\s+\d+\s+of\s+\d+',               # "Page 1 of 6"
        r'^\s*\d+\s*$',                           # Lone page numbers
        # r'Questions:\s+Call.*',                 # PRESERVE THIS - helpful for carrier ID
        r'If you need.*languages?.*',             # Language access notices
        r'This information.*standardized format', # Standard footer text
        r'\bOMB\s+Control\s+Number\b.*',          # OMB control number lines
        r'^\s*[-–—]{3,}\s*$',                     # Divider lines (---) 
        r'^\s*[_]{3,}\s*$',                       # Underline dividers
        # r'www\.[a-zA-Z0-9./\-]+',               # PRESERVE THIS - helpful for carrier ID
        # r'https?://[^\s]+',                      # PRESERVE THIS - helpful for carrier ID
    ]

    KEEP_PATTERNS = [
        r'Coverage Period:',
        r'Coverage for:',
        r'Plan Type:',
        r'Summary of Benefits and Coverage: What this Plan Covers & What You Pay for Covered Services',
    ]

    def clean(self, raw_text: str) -> str:
        """Apply all cleaning steps and return cleaned text."""
        text = raw_text
        original_len = len(text)

        # Step 1: Fix encoding artifacts
        text = text.replace('\u2018', "'").replace('\u2019', "'")  # curly quotes
        text = text.replace('\u201c', '"').replace('\u201d', '"')  # curly double quotes
        text = text.replace('\u2013', '-').replace('\u2014', '-')  # em/en dashes
        text = text.replace('\u00ae', '(R)').replace('\u2122', '(TM)')  # ® ™
        text = text.replace('\x0c', '\n')  # form feed (page break char)

        # Step 2: Fix hyphenated line breaks (word split across lines)
        text = re.sub(r'-\n(\w)', r'\1', text)

        # Step 3: Remove boilerplate patterns (line by line)
        lines = text.split('\n')
        cleaned_lines = []
        removed_lines = 0
        for line in lines:
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in self.KEEP_PATTERNS):
                cleaned_lines.append(line)
                continue

            skip = False
            for pattern in self.BOILERPLATE_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    skip = True
                    removed_lines += 1
                    break
            if not skip:
                cleaned_lines.append(line)
        text = '\n'.join(cleaned_lines)

        # Step 4: Collapse runs of whitespace (but preserve newlines as separators)
        text = re.sub(r'[ \t]+', ' ', text)      # Collapse horizontal space
        text = re.sub(r'\n{3,}', '\n\n', text)   # Max 2 consecutive newlines

        # Step 5: Final strip
        cleaned_text = text.strip()
        
        # Log cleaning summary
        print(f"  [CLEAN] Original: {original_len} chars, Removed {removed_lines} boilerplate lines, Final: {len(cleaned_text)} chars")
        
        return cleaned_text
