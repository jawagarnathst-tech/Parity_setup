import json
import os
import glob
from dotenv import load_dotenv
from src.extractors.universal_extractor import UniversalExtractor
from src.validation.rules_engine import RulesEngine
from src.output.excel_writer import ExcelWriter
from src.output.report_generator import ReportGenerator

def run_pipeline():
    load_dotenv()
    input_folder = r"data\input_pdfs"
    template_folder = r"data\Template"
    default_template = os.path.join(template_folder, "Current Plan - Template.xlsx")
    sample_template = os.path.join(template_folder, "sample template.xlsx")
    if os.path.exists(default_template):
        template_path = default_template
    elif os.path.exists(sample_template):
        template_path = sample_template
    else:
        templates = glob.glob(os.path.join(template_folder, "*.xlsx"))
        if not templates:
            raise FileNotFoundError(f"Template file not found in {template_folder}")
        template_path = templates[0]
        if len(templates) > 1:
            print(f"  [WARN] Multiple Excel templates found in {template_folder}; using {os.path.basename(template_path)}")
    print(f"  [TEMPLATE] Using Excel template: {os.path.basename(template_path)}")
    output_dir = r"data\output"

    # Ensure all output directories exist before processing
    for subdir in ["01_raw_text", "03_parsed_json", "04_reports", "05_final_excel"]:
        os.makedirs(os.path.join(output_dir, subdir), exist_ok=True)

    extensions = ['*.pdf', '*.docx', '*.doc', '*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff']
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(input_folder, ext)))
    
    if not files:
        print(f"No files found in {input_folder}!")
        return

    extractor = UniversalExtractor()
    rules = RulesEngine()
    reporter = ReportGenerator()
    
    all_data = []

    # Process ALL files in the input folder
    for file_path in files:
        filename = os.path.basename(file_path)
        base_name = os.path.splitext(filename)[0]
        print(f"Processing {filename}...")
        
        try:
            # Save raw (cleaned) text for debugging and audit
            raw_text_path = os.path.join(output_dir, "01_raw_text", f"{base_name}.txt")
            schema_model = extractor.extract_text(file_path, save_raw_path=raw_text_path, filename=filename)
            schema_dict = schema_model.model_dump()
            validated_dict, report = rules.validate_and_score(schema_dict, base_name)
            
            json_path = os.path.join(output_dir, "03_parsed_json", f"{base_name}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(validated_dict, f, indent=2)
                
            reporter.generate(report, os.path.join(output_dir, "04_reports", f"{base_name}_report.json"))
            all_data.append(validated_dict)
            print(f"  [OK] {filename} — confidence: {report.get('confidence_score', 'N/A')}")
        except Exception as e:
            print(f"  [FAIL] {file_path}: {e}")

    if not all_data:
        print("No data extracted. Aborting Excel generation.")
        return

    print(f"\nWriting consolidated Excel file ({len(all_data)} plan(s))...")
    writer = ExcelWriter("configs/template_mapping.json")
    excel_out = os.path.join(output_dir, "05_final_excel", "final_batch_output.xlsx")
    writer.write_consolidated(all_data, template_path, excel_out)
    print(f"Pipeline Complete! Output saved to {excel_out}")

if __name__ == "__main__":
    run_pipeline()
