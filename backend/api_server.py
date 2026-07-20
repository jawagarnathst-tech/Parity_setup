"""
SBC Intellect API Server
Exposes the extraction pipeline as a REST API for the frontend
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from fastapi import FastAPI, File, UploadFile, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import uuid
import logging
from pathlib import Path
from dotenv import load_dotenv

from src.extractors.universal_extractor import UniversalExtractor
from src.validation.rules_engine import RulesEngine
from src.output.excel_writer import ExcelWriter

load_dotenv()

app = FastAPI(title="SBC Intellect API", version="1.0.0")

# Configure CORS to allow frontend requests from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("api_server")

BACKEND_DIR = Path(__file__).resolve().parent

# Global task store (in production, use database or Redis)
TASKS = {}
UPLOAD_DIR = BACKEND_DIR / "data/uploads"
OUTPUT_DIR = BACKEND_DIR / "data/output"

# Ensure directories exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    logger.info("Health check requested")
    return {
        "status": "ok",
        "service": "SBC Intellect API",
        "version": "1.0.0"
    }


@app.get("/api/jobs")
async def list_jobs():
    """Return a list of current extraction jobs."""
    return [{"task_id": tid, **info} for tid, info in TASKS.items()]


@app.post("/api/extract")
async def extract_file(file: UploadFile = File(...)):
    """
    Upload SBC document (PDF, DOCX, image) and start extraction
    """
    print(f"\n" + "="*60)
    print(f"[NEW UPLOAD] RECEIVED: {file.filename}")
    print("="*60)
    logger.info(f"Incoming Extraction Request: {file.filename}")

    if not file.filename:
        logger.error("No filename provided")
        raise HTTPException(status_code=400, detail="No filename provided")

    # Validate file type
    allowed_extensions = {'.pdf', '.docx', '.doc', '.jpg', '.jpeg', '.png', '.bmp', '.tiff'}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        logger.error(f"Unsupported file type {file_ext}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
        )

    # Generate task ID
    task_id = str(uuid.uuid4())
    logger.info(f"Task ID generated: {task_id}")

    # Save uploaded file
    upload_path = UPLOAD_DIR / f"{task_id}_{file.filename}"
    try:
        content = await file.read()
        with open(upload_path, "wb") as f:
            f.write(content)
        logger.info(f"File saved to: {upload_path}")
    except Exception as e:
        logger.error(f"Error saving file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # Initialize task tracking
    TASKS[task_id] = {
        "fileName": file.filename,
        "status": "processing",
        "progress": 10,
        "uploadPath": str(upload_path),
        "results": None,
        "error": None,
    }

    # Run extraction
    print(f"  [Setup] Initializing task ID: {task_id}")
    try:
        results = await run_extraction(task_id, upload_path, file.filename)
        TASKS[task_id]["status"] = "completed"
        TASKS[task_id]["progress"] = 100
        TASKS[task_id]["results"] = results
        logger.info(f"Extraction Completed Successfully: {file.filename}")
    except Exception as e:
        logger.error(f"Extraction Failed: {e}")
        TASKS[task_id]["status"] = "failed"
        TASKS[task_id]["error"] = str(e)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")

    return {
        "task_id": task_id,
        "fileName": file.filename,
        "status": "completed",
        "message": "Extraction completed successfully"
    }


@app.get("/api/extract/{task_id}")
async def get_extraction_status(task_id: str):
    """
    Get extraction status and results
    """
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    task = TASKS[task_id]
    return {
        "task_id": task_id,
        "fileName": task["fileName"],
        "status": task["status"],
        "progress": task["progress"],
        "results": task["results"],
        "error": task["error"],
    }


@app.get("/api/download/{task_id}")
async def download_excel(task_id: str):
    """
    Download the generated Excel file
    """
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    task = TASKS[task_id]
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Extraction not completed yet")

    excel_path = task["results"].get("excelPath")
    if not excel_path or not Path(excel_path).exists():
        raise HTTPException(status_code=404, detail="Excel file not found")

    return FileResponse(
        path=excel_path,
        filename=f"{task['fileName']}_extraction.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


class MergeJsonRequest(BaseModel):
    task_ids: list[str]


@app.post("/api/merge-json")
async def merge_json(request: MergeJsonRequest):
    """
    Merge the JSON outputs from multiple processed tasks into a single downloadable JSON file.

    Expects a JSON body: { "task_ids": ["<task_id_1>", "<task_id_2>", ...] }
    Returns a merged JSON array: [{ "filename": "...", "data": { ... } }, ...]
    """
    if not request.task_ids:
        raise HTTPException(status_code=400, detail="No task IDs provided.")

    merged: list[dict] = []

    for task_id in request.task_ids:
        if task_id not in TASKS:
            logger.warning(f"[merge-json] Task ID not found: {task_id}")
            continue

        task = TASKS[task_id]
        if task.get("status") != "completed":
            logger.warning(f"[merge-json] Task not completed, skipping: {task_id}")
            continue

        json_path_str = task.get("results", {}).get("jsonPath")
        if not json_path_str:
            logger.warning(f"[merge-json] No jsonPath stored for task: {task_id}")
            continue

        json_path = Path(json_path_str)
        if not json_path.exists():
            logger.warning(f"[merge-json] JSON file does not exist: {json_path}")
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged.append({
                "filename": task["fileName"],
                "data": data,
            })
            logger.info(f"[merge-json] Included task {task_id} ({task['fileName']})")
        except Exception as e:
            logger.error(f"[merge-json] Failed to read JSON for task {task_id}: {e}")
            continue

    if not merged:
        raise HTTPException(
            status_code=400,
            detail="No valid processed JSON files found for the provided task IDs."
        )

    # Write merged JSON to a temp file and return as a downloadable response
    tmp_path = OUTPUT_DIR / "merged_output.json"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
    except Exception as e:
        logger.error(f"[merge-json] Failed to write merged JSON: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create merged JSON: {str(e)}")

    return FileResponse(
        path=str(tmp_path),
        filename="merged_output.json",
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=merged_output.json"},
    )


async def run_extraction(task_id: str, file_path: Path, filename: str):
    """
    Run the extraction pipeline
    """
    base_name = file_path.stem

    try:
        print(f"\n📂 Processing File: {filename}")

        # Step 1: Extract text and parse with AI
        print("  ⏳ [Step 1/5] Extracting text & running AI parsing...")
        logger.info("  [Pipeline] Step 1: Text extraction & AI parsing...")
        TASKS[task_id]["progress"] = 25
        extractor = UniversalExtractor()
        raw_text_path = OUTPUT_DIR / "01_raw_text" / f"{task_id}.txt"
        raw_text_path.parent.mkdir(parents=True, exist_ok=True)

        schema_model = extractor.extract_text(str(file_path), save_raw_path=str(raw_text_path), filename=filename)
        schema_dict = schema_model.model_dump()

        # Step 2: Validate and score
        print("  ⏳ [Step 2/5] Validating data & scoring confidence...")
        logger.info("  [Pipeline] Step 2: Validation & scoring...")
        TASKS[task_id]["progress"] = 50
        rules = RulesEngine()
        validated_dict, report = rules.validate_and_score(schema_dict, base_name, raw_text_path=str(raw_text_path))
        confidence = report.get("confidence_score", 0)

        # Step 3: Save JSON
        print("  ⏳ [Step 3/5] Saving structured JSON...")
        logger.info("  [Pipeline] Step 3: Saving structured JSON...")
        TASKS[task_id]["progress"] = 75
        json_path = OUTPUT_DIR / "03_parsed_json" / f"{task_id}.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(validated_dict, f, indent=2)

        # Step 4: Write Excel
        print("  ⏳ [Step 4/5] Generating final Excel mapping...")
        logger.info("  [Pipeline] Step 4: Generating Excel output...")
        TASKS[task_id]["progress"] = 90
        template_folder = BACKEND_DIR / "data/Template"
        sample_template = template_folder / "sample template.xlsx"
        default_template = template_folder / "Current Plan - Template.xlsx"

        if default_template.exists():
            template_path = str(default_template)
        elif sample_template.exists():
            template_path = str(sample_template)
        else:
            raise FileNotFoundError(f"No template found in {template_folder}")

        writer = ExcelWriter(str(BACKEND_DIR / "configs/template_mapping.json"))
        excel_path = OUTPUT_DIR / "05_final_excel" / f"{task_id}.xlsx"
        excel_path.parent.mkdir(parents=True, exist_ok=True)
        writer.write_consolidated([validated_dict], template_path, str(excel_path))

        # Step 5: Prepare results
        print("  ⏳ [Step 5/5] Finalizing results & cleanup...")
        TASKS[task_id]["progress"] = 100
        logger.info("  [Pipeline] Step 5: Cleanup & result preparation...")

        carrier = validated_dict.get("plan_information", {}).get("carrier", "Unknown")
        plan_name = validated_dict.get("plan_information", {}).get("plan_name", "Unknown")

        print(f"\n✅ SUCCESS! Extraction complete for '{filename}'")
        print(f"   ► Carrier: {carrier}")
        print(f"   ► Plan:    {plan_name}")
        print(f"   ► Score:   {confidence}%\n")

        return {
            "carrier": carrier,
            "planName": plan_name,
            "planType": validated_dict.get("plan_information", {}).get("plan_type", "Unknown"),
            "confidence": confidence,
            "excelPath": str(excel_path),
            "jsonPath": str(json_path),
            "flags": report.get("flags", []),
            "planData": validated_dict,
        }

    except Exception as e:
        error_type = type(e).__name__
        error_message = str(e)
        
        # Provide more specific error messages for common issues
        if "timeout" in error_message.lower() or "APITimeoutError" in error_type:
            logger.error(f"  [Pipeline] API Timeout Error: The OpenAI API request timed out. This may be due to network issues or high API load. Please try again.")
            raise HTTPException(
                status_code=503, 
                detail="API request timed out. Please try again in a few moments."
            )
        elif "ConnectTimeout" in error_type or "handshake" in error_message.lower():
            logger.error(f"  [Pipeline] Connection Timeout: Unable to establish connection to OpenAI API. Check network connectivity.")
            raise HTTPException(
                status_code=503, 
                detail="Unable to connect to AI service. Please check your network connection and try again."
            )
        else:
            logger.exception(f"  [Pipeline] Error in run_extraction: {e}")
            TASKS[task_id]["progress"] = 0
            raise


@app.post("/api/batch")
async def batch_extract(files: list[UploadFile] = File(...)):
    """
    Batch extract multiple files
    """
    print(f"\n[API] --- Incoming Batch Extraction Request ({len(files)} files) ---")
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    batch_id = str(uuid.uuid4())
    results = []

    for file in files:
        try:
            task_id = str(uuid.uuid4())
            upload_path = UPLOAD_DIR / f"{task_id}_{file.filename}"

            print(f"\n" + "="*60)
            print(f"🚀 BATCH UPLOAD: Processing '{file.filename}'")
            print("="*60)

            extraction_result = await run_extraction(task_id, upload_path, file.filename)
            results.append({
                "fileName": file.filename,
                "status": "success",
                "data": extraction_result
            })
        except Exception as e:
            print(f"\n❌ FAILED: {file.filename} - {str(e)}\n")
            results.append({
                "fileName": file.filename,
                "status": "failed",
                "error": str(e)
            })

    return {
        "batch_id": batch_id,
        "totalFiles": len(files),
        "status": "completed",
        "results": results
    }


if __name__ == "__main__":
    import uvicorn
    import socket

    def get_free_port() -> int:
        """Get a free port from the OS."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]

    # Use PORT env var if set; otherwise find a free port
    env_port_str = os.getenv('PORT')
    if env_port_str:
        try:
            available_port = int(env_port_str)
        except ValueError:
            available_port = get_free_port()
    else:
        # Default to 8001 or find a free one
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', 8001))
                available_port = 8001
        except OSError:
            available_port = get_free_port()

    def get_local_ip() -> str:
        """Get the local IP address of the machine."""
        try:
            # Create a dummy socket to find the local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "localhost"

    local_ip = get_local_ip()
    print(f"Starting SBC Intellect API Server on http://{local_ip}:{available_port} (also http://localhost:{available_port})")

    frontend_env_path = BACKEND_DIR.parent / "Frontend" / ".env"
    try:
        frontend_env_path.parent.mkdir(parents=True, exist_ok=True)
        with open(frontend_env_path, "w", encoding="utf-8") as f:
            f.write(f"VITE_API_BASE_URL=http://{local_ip}:{available_port}\n")
        print(f"Written VITE_API_BASE_URL=http://{local_ip}:{available_port} -> {frontend_env_path}")
    except Exception as e:
        print(f"WARNING: Could not write frontend .env: {e}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=available_port,
        log_level="info"
    )
