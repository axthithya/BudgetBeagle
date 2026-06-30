export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type AuthResponse = {
  token: string;
  user: { id: number; email: string };
};

export type ScanWarning = {
  service: string;
  resource_id?: string | null;
  code?: string;
  message: string;
  permission?: string;
  operation?: string;
  title?: string;
  resolution?: string;
  severity?: string;
};

export type BillingAmount = {
  name?: string;
  label?: string;
  start?: string;
  end?: string;
  amount_usd: number;
  display: string;
};

export type BillingInsight = {
  type: string;
  severity: string;
  title: string;
  message: string;
  regions?: BillingAmount[];
};

export type BillingContext = {
  status?: "available" | "unavailable" | string;
  source?: string;
  account_id?: string | null;
  selected_region?: string;
  selected_region_label?: string;
  period?: { label?: string; start?: string; end?: string; end_exclusive?: boolean };
  account_total_ytd_usd?: number | null;
  selected_region_ytd_usd?: number | null;
  monthly_account_costs?: BillingAmount[];
  monthly_selected_region_costs?: BillingAmount[];
  service_costs_ytd?: BillingAmount[];
  region_costs_ytd?: BillingAmount[];
  insights?: BillingInsight[];
  error?: { code?: string; message?: string; permission?: string } | null;
};

export type ConfidenceFactor = {
  name: string;
  effect: "positive" | "neutral" | "negative" | string;
  reason: string;
};

export type ReportConfidence = {
  score?: number;
  label: string;
  level?: string;
  basis?: string;
  factors?: ConfidenceFactor[];
};

export type ReportMetrics = {
  account_total_ytd_usd?: number | null;
  account_total_ytd_display?: string;
  selected_region_ytd_usd?: number | null;
  selected_region_ytd_display?: string;
  monthly_account_average_usd?: number | null;
  monthly_account_average_display?: string;
  monthly_region_average_usd?: number | null;
  monthly_region_average_display?: string;
  monthly_savings_display?: string;
  yearly_savings_display?: string;
  confidence_score?: number;
  confidence_label?: string;
  unutilized_count?: number;
};

export type AwsCommand = {
  text: string;
  risk: "read-only" | "reversible" | "destructive" | string;
  risk_label: string;
  operation: string;
  valid: boolean;
};

export type Issue = {
  id?: string;
  category?: "Confirmed issue" | "Recommendation" | "Observation" | string;
  service?: string;
  resource_id: string;
  issue_type: string;
  severity: "high" | "medium" | "low" | string;
  confidence?: "high" | "medium" | "low" | string;
  confidence_score?: number;
  finding_confidence?: ReportConfidence;
  savings_confidence?: ReportConfidence;
  explanation: string;
  ai_explanation?: string;
  evidence?: Record<string, unknown>;
  pricing_status?: string;
  pricing_source?: string | null;
  pricing_basis?: string;
  savings_basis?: string;
  estimated_monthly_savings: string | number | null;
  estimated_monthly_savings_display?: string;
  maximum_monthly_avoidable_cost_display?: string;
  recommendation?: string;
  ai_recommendation?: string;
  action_risk?: string;
  command?: AwsCommand | null;
  fix_command?: string;
};

export type AnalysisStatus =
  | "queued"
  | "running"
  | "completed"
  | "completed_with_warnings"
  | "failed"
  | "cancelled"
  | "interrupted"
  | string;

export type AnalysisRecord = {
  id: number;
  user_id: number;
  region: string;
  scan_target: string;
  resources_scanned: number;
  issues_found: number;
  estimated_savings: string;
  analysis_result: AnalysisResult | { error?: string; reason?: string } | Record<string, never>;
  status: AnalysisStatus;
  created_at: string | null;
};

export type AnalysisReportSummary = {
  status?: string;
  summary: string;
  yearly_savings?: { amount_usd?: number | null; display?: string; basis?: string };
  estimated_monthly_savings: string | number | null;
  estimated_monthly_savings_display?: string;
  potential_monthly_savings?: { amount_usd?: number | null; display?: string; basis?: string };
  potential_maximum_avoidable_cost?: { amount_usd?: number | null; display?: string; basis?: string };
  savings_confidence?: ReportConfidence;
  resources_scanned: number;
  issues_found: number;
  confirmed_issues?: number;
  recommendations?: number;
  observations?: number;
  warnings_count?: number;
  notes?: string[];
};

export type ServiceCoverage = {
  service: string;
  status: "completed" | "completed_with_warnings" | "no_resources" | "skipped" | "failed" | string;
  count: number;
  label?: string;
};

export type AnalysisResult = {
  schema_version?: string;
  region?: string;
  resource_group?: string | null;
  report: AnalysisReportSummary;
  scan: {
    account_id?: string | null;
    identity_arn?: string | null;
    region?: string;
    resource_group?: string | null;
    errors?: { service: string; code: string; message: string }[];
    warnings?: ScanWarning[];
    billing?: BillingContext;
    resources?: unknown[];
  };
  resources: unknown[];
  findings: Issue[];
  warnings: ScanWarning[];
  billing?: BillingContext;
  metrics?: ReportMetrics;
  scan_confidence?: ReportConfidence;
  service_coverage?: ServiceCoverage[];
  ai_enrichment?: { status?: "none" | "partial" | "completed" | "failed" | string; summary?: string; notes?: string[] };
  analysis?: Partial<AnalysisReportSummary>;
};

export type AwsStatus = {
  connected: boolean;
  connection_status: "connected" | "connected_with_limited_permissions" | "not_connected";
  account_id_masked: string | null;
  identity_type: string | null;
  identity_name: string | null;
  default_region: string;
  required_permissions: { available: string[]; missing: string[] };
  optional_permissions: { available: string[]; missing: string[] };
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

export async function apiFetchBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    throw new Error(`Request failed with ${response.status}`);
  }
  return response.blob();
}

export function websocketUrl(path: string) {
  const url = new URL(API_BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return `${url.origin}${path}`;
}
