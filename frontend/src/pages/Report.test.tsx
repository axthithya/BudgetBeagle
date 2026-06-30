import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Report from "./Report";

const canonicalRecord = {
  id: 42,
  user_id: 7,
  region: "us-east-1",
  scan_target: "whole-region",
  resources_scanned: 2,
  issues_found: 1,
  estimated_savings: "Not enough data",
  status: "completed_with_warnings",
  created_at: "2026-06-30T12:00:00Z",
  analysis_result: {
    schema_version: "2.0",
    report: {
      status: "completed_with_warnings",
      summary: "Canonical summary rendered from the Phase 1 schema.",
      resources_scanned: 2,
      issues_found: 1,
      confirmed_issues: 1,
      recommendations: 0,
      observations: 1,
      warnings_count: 1,
      estimated_monthly_savings: null,
      estimated_monthly_savings_display: "Not enough data",
      yearly_savings: { amount_usd: null, display: "Not enough data" },
      savings_confidence: { label: "Not applicable", level: "not_applicable" },
    },
    scan: { account_id: "****-****-2560", region: "us-east-1" },
    resources: [
      { service: "EC2", id: "i-0123456789abcdef0123456789abcdef", state: "running", type_or_sku: "t3.micro", metrics: { avg_cpu_14d: 2.4 } },
      { service: "S3", id: "budgetbeagle-extremely-long-bucket-name-for-layout-proof", state: "active", type_or_sku: "bucket", metrics: { lifecycle_status: { status: "unknown" } } },
    ],
    findings: [{
      id: "ebs:vol-0abc:test",
      category: "Confirmed issue",
      service: "EBS",
      resource_id: "vol-0abcdef1234567890",
      issue_type: "Unattached EBS volume",
      severity: "high",
      confidence: "high",
      confidence_score: 90,
      finding_confidence: { score: 90, label: "High", level: "high" },
      explanation: "The volume is not attached.",
      evidence: { Attached: "No" },
      pricing_status: "unavailable",
      pricing_basis: "Current regional EBS storage price could not be verified.",
      savings_basis: "Unattached storage is deterministic waste, but monthly storage cost was not priced.",
      estimated_monthly_savings: null,
      estimated_monthly_savings_display: "Not enough data",
      recommendation: "Create and verify a snapshot before deleting.",
      action_risk: "Destructive. Create and verify a snapshot first.",
      command: { text: "aws ec2 delete-volume --region us-east-1 --volume-id vol-0abcdef1234567890", risk: "destructive", risk_label: "Destructive", operation: "delete", valid: true },
    }],
    warnings: [{ service: "S3", resource_id: "budgetbeagle-extremely-long-bucket-name-for-layout-proof", code: "AccessDenied", message: "Lifecycle unknown", permission: "s3:GetLifecycleConfiguration", resolution: "Add optional read-only permission." }],
    billing: {
      status: "available",
      source: "AWS Cost Explorer",
      period: { label: "2026 YTD" },
      account_id: "****-****-2560",
      selected_region_label: "US East (N. Virginia)",
      account_total_ytd_usd: 12.34,
      selected_region_ytd_usd: 4.56,
      monthly_account_costs: [{ label: "Jun 2026", amount_usd: 4.56, display: "$4.56" }],
      service_costs_ytd: [{ name: "Amazon Elastic Compute Cloud", amount_usd: 4.56, display: "$4.56" }],
      region_costs_ytd: [{ name: "us-east-1", amount_usd: 4.56, display: "$4.56" }],
    },
    metrics: { account_total_ytd_display: "$12.34", selected_region_ytd_display: "$4.56" },
    scan_confidence: { score: 82, label: "High", level: "high", factors: [{ name: "Service scan coverage", effect: "positive", reason: "EC2 and S3 scanned." }] },
    service_coverage: [{ service: "EC2", status: "completed", count: 1 }, { service: "S3", status: "completed_with_warnings", count: 1 }],
    ai_enrichment: { status: "none", notes: [] },
  },
};

function renderReport() {
  render(
    <MemoryRouter initialEntries={["/report/42"]}>
      <Routes>
        <Route path="/report/:analysisId" element={<Report />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ analysis: canonicalRecord }), { status: 200, headers: { "Content-Type": "application/json" } })));
  localStorage.setItem("token", "test-token");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Report Phase 1 schema and accessibility behavior", () => {
  it("renders canonical report fields without waiting forever", async () => {
    renderReport();
    expect(await screen.findByRole("heading", { name: "BudgetBeagle Report" })).toBeInTheDocument();
    expect(screen.getByText("Canonical summary rendered from the Phase 1 schema.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /findings/i }));
    expect(screen.getByText("High 90% finding confidence")).toBeInTheDocument();
    expect(screen.getByText("Savings confidence not applicable without numeric savings.")).toBeInTheDocument();
  });

  it("supports arrow-key tab navigation", async () => {
    const user = userEvent.setup();
    renderReport();
    const overview = await screen.findByRole("tab", { name: /overview/i });
    overview.focus();
    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(screen.getByRole("tab", { name: /billing/i })).toHaveAttribute("aria-selected", "true"));
    await user.keyboard("{End}");
    await waitFor(() => expect(screen.getByRole("tab", { name: /warnings/i })).toHaveAttribute("aria-selected", "true"));
  });
});
