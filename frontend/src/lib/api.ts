export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type AuthResponse = {
  token: string;
  user: { id: number; email: string };
};

export type ScanWarning = {
  service: string;
  resource_id?: string | null;
  region?: string | null;
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
  amount_usd: number | string;
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
  selected_regions?: string[];
  selected_region_count?: number;
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

export type ServiceCoverageSummary = {
  total_supported_services?: number;
  services_scanned?: number;
  services_containing_resources?: number;
  resources_discovered?: number;
  failed_services?: number;
  skipped_services?: number;
  services_scanned_display?: string;
  services_containing_resources_display?: string;
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
  services_scanned?: number;
  total_supported_services?: number;
  services_containing_resources?: number;
  resources_discovered?: number;
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
  category?: "confirmed_issue" | "recommendation" | "observation" | "Confirmed issue" | "Recommendation" | "Observation" | string;
  category_label?: string;
  service?: string;
  region?: string;
  scope?: string;
  source?: string;
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
  confirmed_issues?: number;
  recommendations?: number;
  observations?: number;
  actionable_findings?: number;
  service_coverage_summary?: ServiceCoverageSummary;
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
  service_coverage_summary?: ServiceCoverageSummary;
  resources_scanned: number;
  issues_found: number;
  confirmed_issues?: number;
  recommendations?: number;
  observations?: number;
  actionable_findings?: number;
  warnings_count?: number;
  notes?: string[];
};

export type ServiceCoverage = {
  service: string;
  status: "completed" | "completed_with_warnings" | "no_resources" | "skipped" | "failed" | string;
  count: number;
  label?: string;
  scanned?: boolean;
  has_resources?: boolean;
};

export type RegionMode = "single_region" | "selected_regions" | "all_enabled_regions";

export type RegionScanResult = {
  region: string;
  status: "completed" | "completed_with_warnings" | "failed" | "skipped" | string;
  resources_discovered?: number;
  findings_generated?: number;
  warning_count?: number;
  warnings?: ScanWarning[];
  error_category?: string | null;
  safe_error_message?: string | null;
  services_attempted?: string[];
  services_completed?: string[];
  services_failed?: string[];
};

export type AnalysisResult = {
  schema_version?: string;
  region?: string;
  resource_group?: string | null;
  region_mode?: RegionMode | string;
  requested_regions?: string[];
  resolved_regions?: string[];
  region_count?: number;
  regional_results?: RegionScanResult[];
  partial_failure_warnings?: ScanWarning[];
  regional_resources?: unknown[];
  global_resources?: unknown[];
  regional_findings?: Issue[];
  global_findings?: Issue[];
  report: AnalysisReportSummary;
  scan: {
    account_id?: string | null;
    identity_arn?: string | null;
    region?: string;
    resource_group?: string | null;
    region_mode?: RegionMode | string;
    requested_regions?: string[];
    resolved_regions?: string[];
    regional_results?: RegionScanResult[];
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

type ApiFetchOptions = RequestInit & { authRequired?: boolean };
type AuthListener = () => void;

export const AUTH_EXPIRED_EVENT = "budgetbeagle:auth-expired";

let authInitialized = false;
let unauthorizedHandled = false;
let resolveAuthReady: (() => void) | null = null;
let authReadyPromise = new Promise<void>((resolve) => {
  resolveAuthReady = resolve;
});
const authListeners = new Set<AuthListener>();
const pendingControllers = new Set<AbortController>();
const PUBLIC_PATHS = new Set(["/api/auth/login", "/api/auth/signup", "/api/health"]);

export class AuthRequiredError extends Error {
  constructor(message = "Authentication is required.") {
    super(message);
    this.name = "AuthRequiredError";
  }
}

export function initializeAuth() {
  if (authInitialized) return;
  authInitialized = true;
  resolveAuthReady?.();
  notifyAuthListeners();
}

export function isAuthInitialized() {
  return authInitialized;
}

export function subscribeAuthState(listener: AuthListener) {
  authListeners.add(listener);
  return () => authListeners.delete(listener);
}

function notifyAuthListeners() {
  for (const listener of authListeners) listener();
}

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
  unauthorizedHandled = false;
  initializeAuth();
  notifyAuthListeners();
}

export function clearAuth() {
  localStorage.removeItem("token");
  localStorage.removeItem("user");
  notifyAuthListeners();
}

export function cancelPendingRequests() {
  for (const controller of Array.from(pendingControllers)) controller.abort();
  pendingControllers.clear();
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const response = await request(path, options, true);
  return response.json() as Promise<T>;
}

export async function apiFetchBlob(path: string, options: ApiFetchOptions = {}): Promise<Blob> {
  const response = await request(path, options, false);
  return response.blob();
}

async function request(path: string, options: ApiFetchOptions, jsonRequest: boolean): Promise<Response> {
  const authRequired = options.authRequired ?? !PUBLIC_PATHS.has(path);
  if (authRequired) await waitForAuthInitialization(options.signal);

  const headers = new Headers(options.headers);
  if (jsonRequest && !headers.has("Content-Type") && options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const token = getToken();
  if (authRequired) {
    if (!token) throw new AuthRequiredError();
    headers.set("Authorization", `Bearer ${token}`);
  } else if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const controller = new AbortController();
  pendingControllers.add(controller);
  const signal = mergeSignals(controller, options.signal);
  const { authRequired: _authRequired, signal: _signal, ...fetchOptions } = options;

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...fetchOptions,
      headers,
      signal,
    });

    if (response.status === 401 && authRequired) {
      handleUnauthorized();
    }

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

    return response;
  } finally {
    pendingControllers.delete(controller);
  }
}

function mergeSignals(controller: AbortController, external?: AbortSignal | null): AbortSignal {
  if (!external) return controller.signal;
  if (external.aborted) controller.abort();
  else external.addEventListener("abort", () => controller.abort(), { once: true });
  return controller.signal;
}

async function waitForAuthInitialization(signal?: AbortSignal | null) {
  if (authInitialized) return;
  await Promise.race([
    authReadyPromise,
    new Promise<void>((_, reject) => {
      if (!signal) return;
      if (signal.aborted) reject(new DOMException("Aborted", "AbortError"));
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }),
  ]);
}

function handleUnauthorized() {
  if (unauthorizedHandled) return;
  unauthorizedHandled = true;
  clearAuth();
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
}

export function websocketUrl(path: string) {
  const url = new URL(API_BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return `${url.origin}${path}`;
}

export function resetAuthForTests(initialized = false) {
  authInitialized = initialized;
  unauthorizedHandled = false;
  if (initialized) {
    authReadyPromise = Promise.resolve();
    resolveAuthReady = null;
  } else {
    authReadyPromise = new Promise<void>((resolve) => {
      resolveAuthReady = resolve;
    });
  }
  pendingControllers.clear();
  authListeners.clear();
}
