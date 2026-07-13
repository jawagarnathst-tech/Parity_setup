import json
import os

class ReportGenerator:
    def generate(self, report_data: dict, output_path: str):
        try:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Write the report
            with open(output_path, 'w') as f:
                json.dump(report_data, f, indent=2)
        except Exception as e:
            print(f"[ERROR] Failed to save report to {output_path}: {e}")
