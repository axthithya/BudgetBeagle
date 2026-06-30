export const ACTIVE_ANALYSIS_STORAGE_KEY = "budgetbeagle.activeAnalysisId";

export const TERMINAL_ANALYSIS_STATUSES = [
  "completed",
  "completed_with_warnings",
  "failed",
  "cancelled",
  "interrupted",
] as const;

const SUCCESS_STATUSES = new Set(["completed", "completed_with_warnings"]);
const FAILURE_STATUSES = new Set(["failed", "cancelled", "interrupted"]);
const TERMINAL_STATUSES = new Set<string>(TERMINAL_ANALYSIS_STATUSES);

export function isTerminalAnalysisStatus(status?: string | null): boolean {
  return Boolean(status && TERMINAL_STATUSES.has(status));
}

export function isSuccessfulAnalysisStatus(status?: string | null): boolean {
  return Boolean(status && SUCCESS_STATUSES.has(status));
}

export function isFailureAnalysisStatus(status?: string | null): boolean {
  return Boolean(status && FAILURE_STATUSES.has(status));
}

export function getStoredActiveAnalysisId(storage: Storage = localStorage): number | null {
  const raw = storage.getItem(ACTIVE_ANALYSIS_STORAGE_KEY);
  if (!raw) return null;
  const value = Number(raw);
  return Number.isInteger(value) && value > 0 ? value : null;
}

export function storeActiveAnalysisId(analysisId: number, storage: Storage = localStorage): void {
  storage.setItem(ACTIVE_ANALYSIS_STORAGE_KEY, String(analysisId));
}

export function clearStoredActiveAnalysisId(analysisId?: number, storage: Storage = localStorage): void {
  if (analysisId === undefined || getStoredActiveAnalysisId(storage) === analysisId) {
    storage.removeItem(ACTIVE_ANALYSIS_STORAGE_KEY);
  }
}
