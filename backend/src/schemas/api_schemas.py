from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict

class HealthResponse(BaseModel):
    status: str = Field(..., description="Current status of the API", example="ok")
    service: str = Field(..., description="Name of the service", example="SBC Intellect API")
    version: str = Field(..., description="Version of the API", example="1.0.0")

class ExtractionResult(BaseModel):
    carrier: str = Field(..., description="Extracted carrier name")
    planName: str = Field(..., description="Extracted plan name")
    planType: str = Field(..., description="Extracted plan type")
    confidence: float = Field(..., description="Overall confidence score for the extraction (0-100)")
    excelPath: str = Field(..., description="Path to the generated Excel file on the server")
    jsonPath: str = Field(..., description="Path to the generated JSON file on the server")
    flags: List[str] = Field(default_factory=list, description="Any validation warnings or flags")
    planData: Dict[str, Any] = Field(..., description="The raw validated JSON structure")

class JobStatus(BaseModel):
    task_id: str = Field(..., description="Unique identifier for the extraction task")
    fileName: str = Field(..., description="Original filename that was uploaded")
    status: str = Field(..., description="Current status (processing, completed, failed)")
    progress: int = Field(..., description="Percentage of completion (0-100)")
    uploadPath: str = Field(..., description="Path to the uploaded file on the server")
    results: Optional[ExtractionResult] = Field(None, description="Detailed extraction results if completed")
    error: Optional[str] = Field(None, description="Error message if the task failed")

class ExtractionResponse(BaseModel):
    task_id: str = Field(..., description="Unique identifier generated for the task")
    fileName: str = Field(..., description="Name of the uploaded file")
    status: str = Field(..., description="Status of the extraction request (e.g., completed, processing)")
    message: str = Field(..., description="Informational message about the request")
    excelDownloadUrl: Optional[str] = Field(None, description="Direct URL to download the generated Excel file")
    jsonDownloadUrl: Optional[str] = Field(None, description="Direct URL to download the generated JSON file")

class MergeJsonRequest(BaseModel):
    task_ids: List[str] = Field(..., description="List of task IDs to merge the JSON outputs for")

class BatchExtractionResultItem(BaseModel):
    fileName: str = Field(..., description="Name of the uploaded file")
    status: str = Field(..., description="Status of the specific file's extraction (success, failed)")
    data: Optional[ExtractionResult] = Field(None, description="Detailed extraction results if success")
    error: Optional[str] = Field(None, description="Error message if failed")

class BatchExtractionResponse(BaseModel):
    batch_id: str = Field(..., description="Unique identifier for the batch process")
    totalFiles: int = Field(..., description="Number of files processed in this batch")
    status: str = Field(..., description="Status of the batch request")
    results: List[BatchExtractionResultItem] = Field(..., description="List of results for each file")

class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Detailed error message")
