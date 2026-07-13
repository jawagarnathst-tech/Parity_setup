# SBC PDF Automation Platform

This is an enterprise-grade automation pipeline designed to extract complex tabular data from Health Insurance SBC (Summary of Benefits and Coverage) PDFs across various carriers and normalize it into a unified Excel template.

## How It Works

The platform utilizes a completely decoupled, config-driven architecture powered by Large Language Models:
1. **Universal Extraction**: The system uses `pdfplumber` to extract the raw, scrambled text from any SBC PDF regardless of the carrier's layout.
2. **LLM Translation**: The raw text is securely passed to OpenAI's GPT-4o utilizing **Structured Outputs**. The LLM acts as a semantic parser, interpreting the messy text and coercing it strictly into our `MasterSBCSchema` (defined via Pydantic).
3. **Template Injection**: A configuration file (`template_mapping.json`) defines exactly which cells in the Master Excel template correspond to the JSON fields. The `openpyxl` engine safely injects the data into the blank Excel template without breaking any existing formatting, dropdowns, or formulas.

## Folder Structure

```text
c:\SBC\
├── .env                          # Holds OPENAI_API_KEY
├── configs/
│   └── template_mapping.json     # Maps Pydantic schema fields to Excel cells
├── data/
│   ├── input_pdfs/               # Drop new SBC PDFs here
│   ├── manual_samples/           # Reference manual outputs
│   ├── templates/                # Blank Master Excel templates
│   └── output/
│       ├── 03_parsed_json/       # The raw extracted JSON from OpenAI
│       ├── 04_reports/           # Confidence and Validation QA reports
│       └── 05_final_excel/       # The final mapped Excel documents
├── src/
│   ├── extractors/
│   │   └── universal_extractor.py # The OpenAI LLM extraction engine
│   ├── output/
│   │   ├── excel_writer.py        # openpyxl template mapping logic
│   │   └── report_generator.py    # QA report generation
│   ├── schemas/
│   │   └── master_schema.py       # Pydantic Master Schema definition
│   ├── validation/
│   │   └── rules_engine.py        # Business logic and confidence scoring
│   └── pipeline.py                # Main orchestration script
└── requirements.txt
```

## Setup & Installation

1. **Install Dependencies:**
   Ensure you have Python installed, then install the required libraries:
   ```bash
   pip install -r requirements.txt
   ```

2. **Environment Variables:**
   Ensure you have an `.env` file in the root `c:\SBC\` directory containing your API key:
   ```env
   OPENAI_API_KEY=sk-your-api-key-here
   ```

## Usage

1. Place one or more SBC PDFs into `data/input_pdfs/`.
2. Ensure your blank master template is located at `data/Template/Current Plan - Template.xlsx`.
3. Run the pipeline:
   ```bash
   python -m src.pipeline
   ```
4. The parsed JSON, QA reports, and final populated Excel sheets will be generated in their respective subfolders under `data/output/`.

## Modifying the Schema

If you need to extract new data points from future PDFs:
1. Add the new field to the Pydantic models in `src/schemas/master_schema.py`. The OpenAI structured output engine will automatically start extracting it.
2. Update `configs/template_mapping.json` to point the new field to the correct target cell in the Excel template.
