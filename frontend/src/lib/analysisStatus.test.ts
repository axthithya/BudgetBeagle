import { describe, expect, it } from "vitest";
import { ACTIVE_ANALYSIS_STORAGE_KEY, clearStoredActiveAnalysisId, getStoredActiveAnalysisId, isFailureAnalysisStatus, isSuccessfulAnalysisStatus, isTerminalAnalysisStatus, storeActiveAnalysisId } from "./analysisStatus";

describe("analysis status helpers", () => {
  it("classifies terminal, successful, and failure statuses", () => {
    expect(isTerminalAnalysisStatus("completed_with_warnings")).toBe(true);
    expect(isSuccessfulAnalysisStatus("completed_with_warnings")).toBe(true);
    expect(isFailureAnalysisStatus("cancelled")).toBe(true);
    expect(isTerminalAnalysisStatus("running")).toBe(false);
  });

  it("persists and clears browser refresh recovery state", () => {
    storeActiveAnalysisId(42);
    expect(localStorage.getItem(ACTIVE_ANALYSIS_STORAGE_KEY)).toBe("42");
    expect(getStoredActiveAnalysisId()).toBe(42);
    clearStoredActiveAnalysisId(41);
    expect(getStoredActiveAnalysisId()).toBe(42);
    clearStoredActiveAnalysisId(42);
    expect(getStoredActiveAnalysisId()).toBeNull();
  });
});
