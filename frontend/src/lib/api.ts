export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type AuthResponse = {
  token: string;
  user: { id: number; email: string };
};

export type AnalysisRecord = {
  id: number;
  user_id: number;
  region: string;
  scan_target: string;
  resources_scanned: number;
  issues_found: number;
  estimated_savings: string;
  analysis_result: AnalysisResult | { error?: string } | Record<string, never>;
  status: "queued" | "running" | "completed" | "failed" | string;
  created_at: string | null;
};

export type Issue = {
  resource_id: string;
  issue_type: string;
  severity: "high" | "medium" | "low" | string;
  explanation: string;
  estimated_monthly_savings: string | number;
  fix_command: string;
};

export type AnalysisResult = {
  region: string;
  resource_group?: string | null;
  scan: {
    resources: unknown[];
    errors?: { service: string; code: string; message: string }[];
  };
  analysis: {
    summary: string;
    issues: Issue[];
    estimated_monthly_savings: string | number;
    resources_scanned: number;
    issues_found: number;
    notes?: string[];
  };
};

export function getToken() {
  return localStorage.getItem("token") ?? "";
}

export function getUserEmail() {
  try {
    return JSON.parse(localStorage.getItem("user") ?? "{}").email ?? "";
  } catch {
    return "";
  }
}

export function setAuth(auth: AuthResponse) {
  localStorage.setItem("token", auth.token);
  localStorage.setItem("user", JSON.stringify(auth.user));
}

export function clearAuth() {
  localStorage.removeItem("token");
  localStorage.removeItem("user");
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail ?? message;
    } catch {
      // Keep the generic status message.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export function websocketUrl(path: string) {
  const url = new URL(API_BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return `${url.origin}${path}`;
}