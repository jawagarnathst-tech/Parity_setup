const getApiBaseUrl = () => {
  // 1. Try environment variable from Vite
  let baseUrl = import.meta.env.VITE_API_BASE_URL;
  
  console.log("[API] VITE_API_BASE_URL env var:", baseUrl);
  
  // 2. Fallback to current window location if baseUrl is missing or set to localhost/127.0.0.1
  // but we are accessing via a different hostname (like a local IP)
  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    const isLocalAccess = hostname === "localhost" || hostname === "127.0.0.1";
    
    console.log("[API] Window hostname:", hostname);
    console.log("[API] Is local access:", isLocalAccess);
    
    if (!baseUrl) {
      // If no env var, assume backend is on the same host as frontend, port 8000
      const url = `http://${hostname}:8000`;
      console.log("[API] No env var, using:", url);
      return url;
    }

    const isBaseUrlLocal = baseUrl.includes("localhost") || baseUrl.includes("127.0.0.1");
    if (isBaseUrlLocal && !isLocalAccess) {
      // Automatically swap localhost for the actual IP the user is using
      const newUrl = baseUrl.replace("localhost", hostname).replace("127.0.0.1", hostname);
      console.log("[API] Replacing localhost with IP:", newUrl);
      return newUrl;
    }
  }

  console.log("[API] Final URL:", baseUrl || "http://localhost:8000");
  return baseUrl || "http://localhost:8000";
};

export const API_BASE_URL = getApiBaseUrl();
console.log("[API] API_BASE_URL initialized as:", API_BASE_URL);

export async function apiFetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  
  console.log("[API FETCH] URL:", url);
  console.log("[API FETCH] Method:", options.method || "GET");
  console.log("[API FETCH] Body type:", options.body instanceof FormData ? "FormData" : typeof options.body);
  
  const headers = new Headers(options.headers || {});
  
  // If sending FormData, do not set Content-Type; browser will set multipart boundary
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  try {
    console.log("[API FETCH] Sending request...");
    const response = await fetch(url, {
      ...options,
      headers,
    });

    console.log("[API FETCH] Response status:", response.status);
    console.log("[API FETCH] Response ok:", response.ok);

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const errorMsg = errorData.detail || `API request failed: ${response.statusText}`;
      console.error("[API FETCH] Error:", errorMsg);
      throw new Error(errorMsg);
    }

    const data = await response.json();
    console.log("[API FETCH] Success, got data");
    return data;
  } catch (error) {
    console.error("[API FETCH] Exception:", error);
    throw error;
  }
}
