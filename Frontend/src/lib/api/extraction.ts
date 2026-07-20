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

export async function mergeJSON(taskIds: string[]): Promise<void> {
  const url = `${API_BASE_URL}/api/merge-json`;
  console.log("[MERGE-JSON] Sending merge request for task IDs:", taskIds);

  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_ids: taskIds }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const errorMsg = errorData.detail || `Merge failed: ${response.statusText}`;
    console.error("[MERGE-JSON] Error:", errorMsg);
    throw new Error(errorMsg);
  }

  // Stream the file blob and trigger download
  const blob = await response.blob();
  const downloadUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = "merged_output.json";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(downloadUrl);
  console.log("[MERGE-JSON] Download triggered successfully.");
}
