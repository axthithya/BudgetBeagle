import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetAuthForTests } from "../lib/api";
import Report from "./Report";

const canonicalRecord = {
  id: 42,
  user_id: 7,
  region: "ap-southeast-1",
  scan_target: "whole-region",
  resources_scanned: 3,
  issues_found: 0,
  confirmed_issues: 0,
  recommendations: 1,
  observations: 1,
  actionable_findings: 1,
  estimated_savings: "Not enough data",
  status: "completed",
  created_at: "2026-06-30T12:00:00Z",
  analysis_result: {
    schema_version: "2.0",
    report: {
      status: "completed",
      summary: "Resources discovered: 3. 0 confirmed issues, 1 recommendation, 1 observation.",
      resources_scanned: 3,
      issues_found: 0,
      confirmed_issues: 0,
      recommendations: 1,
      observations: 1,
      actionable_findings: 1,
      warnings_count: 0,
      estimated_monthly_savings: null,
      estimated_monthly_savings_display: "Not enough data",
      yearly_savings: { amount_usd: null, display: "Not enough data" },
      savings_confidence: { label: "Not applicable", level: "not_applicable" },
      service_coverage_summary: {
        total_supported_services: 7,
        services_scanned: 7,
        services_containing_resources: 3,
        resources_discovered: 3,
        services_scanned_display: "7/7",
        services_containing_resources_display: "3/7",
      },
    },
    scan: { account_id: "****-****-2560", region: "ap-southeast-1", errors: [] },
    resources: [
      { service: "EC2", id: "i-0123456789abcdef0123456789abcdef", state: "running", type_or_sku: "t3.micro", metrics: { cpu_utilization: { average: 0.13, datapoint_count: 22, actual_duration_hours: 22 } } },
      { service: "EBS", id: "vol-0abcdef1234567890", state: "in-use", type_or_sku: "gp3", metrics: { iops: 3000, throughput_mibps: 125 } },
      { service: "S3", id: "budgetbeagle-extremely-long-bucket-name-for-layout-proof", state: "active", type_or_sku: "bucket", metrics: { lifecycle_status: { status: "absent", code: "NoSuchLifecycleConfiguration" } } },
    ],
    findings: [
      {
        id: "ec2:i:test",
        category: "observation",
        category_label: "Observation",
        service: "EC2",
        resource_id: "i-0123456789abcdef0123456789abcdef",
        issue_type: "Low EC2 CPU utilization review candidate",
        severity: "low",
        confidence: "low",
        confidence_score: 55,
        finding_confidence: { score: 55, label: "Low", level: "low" },
        explanation: "More monitoring is needed.",
        evidence: { "Actual covered duration": "22.0 hours" },
        pricing_status: "unavailable",
        pricing_basis: "Pricing unavailable.",
        savings_basis: "Not enough data.",
        estimated_monthly_savings: null,
        estimated_monthly_savings_display: "Not enough data",
        recommendation: "Continue monitoring.",
        action_risk: "No command generated.",
        command: null,
      },
      {
        id: "s3:bucket:test",
        category: "recommendation",
        category_label: "Recommendation",
        service: "S3",
        resource_id: "budgetbeagle-extremely-long-bucket-name-for-layout-proof",
        issue_type: "S3 lifecycle policy review",
        severity: "low",
        confidence: "low",
        confidence_score: 55,
        finding_confidence: { score: 55, label: "Low", level: "low" },
        explanation: "No lifecycle policy was found.",
        evidence: { "Lifecycle status": "Absent", "Stored bytes": "Unknown", "Object count": "Unknown" },
        pricing_status: "unavailable",
        pricing_basis: "S3 savings require more data.",
        savings_basis: "Not enough data to calculate lifecycle transition savings.",
        estimated_monthly_savings: null,
        estimated_monthly_savings_display: "Not enough data",
        recommendation: "Review lifecycle requirements.",
        action_risk: "No command generated because no validated lifecycle transition was selected.",
        command: null,
      },
    ],
    warnings: [],
    billing: {
      status: "available",
      source: "AWS Cost Explorer",
      period: { label: "2026 YTD" },
      account_id: "****-****-2560",
      selected_region_label: "ap-southeast-1",
      account_total_ytd_usd: 0,
      selected_region_ytd_usd: 0,
      monthly_account_costs: [{ label: "May 2026", amount_usd: -0.001, display: "$-0.00" }],
      service_costs_ytd: [
        { name: "Amazon Elastic Compute Cloud", amount_usd: 0, display: "$0.00" },
        { name: "Amazon Simple Storage Service", amount_usd: 0, display: "$0.00" },
      ],
      region_costs_ytd: [{ name: "NoRegion", amount_usd: 0, display: "$0.00" }],
    },
    metrics: { account_total_ytd_display: "$0.00", selected_region_ytd_display: "$0.00", monthly_savings_display: "Not enough data" },
    scan_confidence: { score: 95, label: "High", level: "high", factors: [{ name: "Service scan coverage", effect: "positive", reason: "7/7 supported services completed." }] },
    service_coverage: [
      { service: "EC2", status: "completed", count: 1, scanned: true },
      { service: "EBS", status: "completed", count: 1, scanned: true },
      { service: "S3", status: "completed", count: 1, scanned: true },
      { service: "RDS", status: "no_resources", count: 0, scanned: true },
      { service: "Load Balancing", status: "no_resources", count: 0, scanned: true },
      { service: "Elastic IP", status: "no_resources", count: 0, scanned: true },
      { service: "NAT Gateway", status: "no_resources", count: 0, scanned: true },
    ],
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
  resetAuthForTests(true);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ analysis: canonicalRecord }), { status: 200, headers: { "Content-Type": "application/json" } })));
  localStorage.setItem("token", "test-token");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Report Phase 1 manual regression behavior", () => {
  it("renders canonical counters, service coverage, and separate confidence labels", async () => {
    renderReport();
    expect(await screen.findByRole("heading", { name: "BudgetBeagle Report" })).toBeInTheDocument();
    expect(screen.getByText("Resources discovered: 3. 0 confirmed issues, 1 recommendation, 1 observation.")).toBeInTheDocument();
    expect(screen.getByText("0 confirmed issues")).toBeInTheDocument();
    expect(screen.getByText("1 recommendation - 1 observation - 1 actionable")).toBeInTheDocument();
    expect(screen.getByText("Services scanned: 7/7")).toBeInTheDocument();
    expect(screen.getByText("Services containing resources: 3/7 - Resources discovered: 3")).toBeInTheDocument();
    expect(screen.getByText("95% - High")).toBeInTheDocument();
    expect(screen.getByText("55% - Low average")).toBeInTheDocument();
    expect(screen.getAllByText("Not applicable").length).toBeGreaterThan(0);
  });

  it("normalizes negative zero and preserves zero-cost billing toggle across tabs", async () => {
    const user = userEvent.setup();
    renderReport();
    await screen.findByRole("heading", { name: "BudgetBeagle Report" });
    await user.click(screen.getByRole("tab", { name: /billing/i }));
    expect(screen.getByText("No billable usage detected for this period.")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("$-0.00");
    await user.click(screen.getByRole("button", { name: "Show zero-cost services" }));
    expect(screen.getByRole("button", { name: "Hide zero-cost services" })).toBeInTheDocument();
    expect(screen.getByText("Global / No Region")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /overview/i }));
    await user.click(screen.getByRole("tab", { name: /billing/i }));
    expect(screen.getByRole("button", { name: "Hide zero-cost services" })).toBeInTheDocument();
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
