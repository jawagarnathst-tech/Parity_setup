import { API_BASE_URL, apiFetch } from "./client";

export interface ExtractionRequestResponse {
  task_id: string;
  fileName: string;
  status: "processing" | "completed" | "failed";
  message: string;
}

export interface ExtractionStatusResponse {
  task_id: string;
  fileName: string;
  status: "processing" | "completed" | "failed";
  progress: number;
  results: any | null;
  error: string | null;
}

export async function uploadFile(file: File): Promise<ExtractionRequestResponse> {
  console.log("[EXTRACTION] Starting upload for file:", file.name, "Size:", file.size);
  
  const formData = new FormData();
  formData.append("file", file);

  try {
    console.log("[EXTRACTION] Calling apiFetch...");
    const result = await apiFetch<ExtractionRequestResponse>("/api/extract", {
      method: "POST",
      body: formData,
    });
    console.log("[EXTRACTION] Upload successful:", result);
    return result;
  } catch (error) {
    console.error("[EXTRACTION] Upload failed:", error);
    throw error;
  }
}

export async function getStatus(taskId: string): Promise<ExtractionStatusResponse> {
  return apiFetch<ExtractionStatusResponse>(`/api/extract/${taskId}`);
}

export function getDownloadUrl(taskId: string): string {
  return `${API_BASE_URL}/api/download/${taskId}`;
}
