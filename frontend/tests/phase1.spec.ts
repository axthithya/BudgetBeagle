import { expect, test } from "@playwright/test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

const mockRecord = {
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
      { service: "EBS", id: "vol-0abcdef1234567890abcdef1234567890", state: "in-use", type_or_sku: "gp3", metrics: { iops: 3000, throughput_mibps: 125 } },
      { service: "S3", id: "budgetbeagle-extremely-long-bucket-name-for-layout-proof-abcdefghijklmnopqrstuvwxyz", state: "active", type_or_sku: "bucket", metrics: { lifecycle_status: { status: "absent", code: "NoSuchLifecycleConfiguration" }, bucket_size_bytes: null, object_count: null } },
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
        resource_id: "budgetbeagle-extremely-long-bucket-name-for-layout-proof-abcdefghijklmnopqrstuvwxyz",
        issue_type: "S3 lifecycle policy review",
        severity: "low",
        confidence: "low",
        confidence_score: 55,
        finding_confidence: { score: 55, label: "Low", level: "low" },
        explanation: "No lifecycle policy was found, but savings cannot be calculated without object age, storage class, and transition data.",
        evidence: { "Lifecycle status": "Absent", "Stored bytes": "Unknown", "Object count": "Unknown" },
        pricing_status: "unavailable",
        pricing_basis: "S3 savings require storage class, age distribution, region, and transition cost data.",
        savings_basis: "Not enough data to calculate lifecycle transition savings.",
        estimated_monthly_savings: null,
        estimated_monthly_savings_display: "Not enough data",
        recommendation: "Review lifecycle requirements before making changes.",
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

function makePartialRegionalRecord() {
  const record = JSON.parse(JSON.stringify(mockRecord));
  record.status = "completed_with_warnings";
  record.analysis_result.schema_version = "2.1";
  record.analysis_result.region_mode = "selected_regions";
  record.analysis_result.requested_regions = ["ap-southeast-1", "us-west-2"];
  record.analysis_result.resolved_regions = ["ap-southeast-1", "us-west-2"];
  record.analysis_result.region_count = 2;
  record.analysis_result.report.status = "completed_with_warnings";
  record.analysis_result.report.warnings_count = 1;
  record.analysis_result.regional_results = [
    { region: "ap-southeast-1", status: "completed", resources_discovered: 3, findings_generated: 1, warning_count: 0, warnings: [] },
    { region: "us-west-2", status: "failed", resources_discovered: 0, findings_generated: 0, warning_count: 1, safe_error_message: "Access denied", warnings: [] },
  ];
  record.analysis_result.warnings = [
    { service: "Region", resource_id: "us-west-2", region: "us-west-2", code: "RegionScanFailed", message: "Access denied", resolution: "Retry after checking IAM." },
  ];
  record.analysis_result.partial_failure_warnings = record.analysis_result.warnings;
  return record;
}
type ApiCounts = Record<string, number>;

async function mockApi(page: import("@playwright/test").Page, counts: ApiCounts = {}, options: { analysisRecord?: unknown; regions?: string[] } = {}) {
  await page.addInitScript(() => {
    localStorage.setItem("token", "test-token");
    localStorage.setItem("user", JSON.stringify({ id: 7, email: "phase1@example.com" }));
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = url.pathname;
    counts[key] = (counts[key] ?? 0) + 1;
    expect(request.headers().authorization, `${url.pathname} auth header`).toBe("Bearer test-token");

    if (key === "/api/analyses/42") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ analysis: options.analysisRecord ?? mockRecord }) });
      return;
    }
    if (key === "/api/history") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ analyses: [options.analysisRecord ?? mockRecord] }) });
      return;
    }
    if (key === "/api/regions") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "available", regions: options.regions ?? ["ap-southeast-1", "us-east-1", "us-west-2"] }) });
      return;
    }
    if (key === "/api/aws/status") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          connected: true,
          connection_status: "connected",
          account_id_masked: "****-****-2560",
          identity_type: "user",
          identity_name: "phase1",
          default_region: "ap-southeast-1",
          required_permissions: { available: [], missing: [] },
          optional_permissions: { available: [], missing: [] },
        }),
      });
      return;
    }
    if (key === "/api/resource-groups") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ resource_groups: [] }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });
}

async function expectNoPageHorizontalScroll(page: import("@playwright/test").Page) {
  const overflow = await page.evaluate(() => ({
    html: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }));
  expect(overflow.html, `html overflow ${overflow.html}px`).toBeLessThanOrEqual(1);
  expect(overflow.body, `body overflow ${overflow.body}px`).toBeLessThanOrEqual(1);
}

const viewports = [
  { width: 375, height: 667, label: "375x667" },
  { width: 768, height: 1024, label: "768x1024" },
  { width: 1366, height: 768, label: "1366x768" },
  { width: 1920, height: 1080, label: "1920x1080" },
];

for (const viewport of viewports) {
  test(`manual fixture responsive report ${viewport.label}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await mockApi(page);
    await page.goto("/report/42");
    await expect(page.getByRole("heading", { name: "BudgetBeagle Report" })).toBeVisible();
    await expect(page.getByText("0 confirmed issues", { exact: true })).toBeVisible();
    await expect(page.getByText("1 recommendation - 1 observation - 1 actionable")).toBeVisible();
    await expect(page.getByText("Services scanned: 7/7")).toBeVisible();
    await expect(page.getByText("Services containing resources: 3/7 - Resources discovered: 3")).toBeVisible();
    await expect(page.getByText("95% - High")).toBeVisible();
    await expect(page.getByText("55% - Low average")).toBeVisible();
    await expect(page.getByText("Not applicable").first()).toBeVisible();
    await expectNoPageHorizontalScroll(page);

    await page.getByRole("tab", { name: "Resources" }).click();
    const resourceId = page.getByText("budgetbeagle-extremely-long-bucket-name-for-layout-proof", { exact: false });
    await expect(resourceId.nth(viewport.width < 768 ? 1 : 0)).toBeVisible();
    await expectNoPageHorizontalScroll(page);

    await page.getByRole("tab", { name: "Billing" }).click();
    await expect(page.getByText("No billable usage detected for this period.")).toBeVisible();
    await expect(page.getByText("$-0.00")).toHaveCount(0);
    await page.getByRole("button", { name: "Show zero-cost services" }).click();
    await expect(page.getByRole("button", { name: "Hide zero-cost services" })).toBeVisible();
    await expect(page.getByText("Global / No Region")).toBeVisible();
    await page.getByRole("tab", { name: "Overview" }).click();
    await page.getByRole("tab", { name: "Billing" }).click();
    await expect(page.getByRole("button", { name: "Hide zero-cost services" })).toBeVisible();
    await expectNoPageHorizontalScroll(page);

    await page.getByRole("tab", { name: "Findings" }).click();
    await expect(page.getByText("No command generated because no validated lifecycle transition was selected.")).toBeVisible();
    await expect(page.getByText("aws s3", { exact: false })).toHaveCount(0);
    await expectNoPageHorizontalScroll(page);

    await page.getByRole("tab", { name: "Warnings" }).click();
    await expect(page.getByRole("heading", { name: "No scan warnings" })).toBeVisible();
    await expectNoPageHorizontalScroll(page);
  });
}


test("dashboard multi-region controls are responsive, keyboard accessible, and axe-clean", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Run Analysis" })).toBeVisible();

  await page.getByRole("radio", { name: "Selected regions" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Selected regions" })).toBeVisible();
  await expect(page.getByText("1 selected")).toBeVisible();

  await page.getByRole("button", { name: "Select all" }).click();
  await expect(page.getByText("3 selected")).toBeVisible();
  await page.getByRole("textbox", { name: "Filter regions" }).fill("west");
  await expect(page.getByRole("checkbox", { name: "us-west-2" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "ap-southeast-1" })).toHaveCount(0);

  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(page.getByRole("button", { name: "Run Analysis" })).toBeDisabled();
  await page.getByRole("checkbox", { name: "us-west-2" }).check();
  await expect(page.getByText("1 selected")).toBeVisible();

  await page.getByRole("radio", { name: "All enabled regions" }).click();
  await expect(page.getByText("3 regions resolved by AWS region discovery")).toBeVisible();
  await expectNoPageHorizontalScroll(page);

  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const violations = await page.evaluate(async () => {
    // @ts-expect-error axe is injected by the test.
    const results = await window.axe.run(document);
    return results.violations.map((violation: { id: string; impact: string | null; nodes: unknown[] }) => ({
      id: violation.id,
      impact: violation.impact,
      nodes: violation.nodes.length,
    }));
  });
  expect(violations).toEqual([]);
});

test("partial-success report shows failed regional result and warning recovery text", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 });
  await mockApi(page, {}, { analysisRecord: makePartialRegionalRecord() });
  await page.goto("/report/42");

  await expect(page.getByRole("heading", { name: "Regional Scan Results" })).toBeVisible();
  await expect(page.getByText("us-west-2").first()).toBeVisible();
  await expect(page.getByText("Access denied").first()).toBeVisible();
  await page.getByRole("tab", { name: "Warnings" }).click();
  await expect(page.getByText("Retry after checking IAM.")).toBeVisible();
  await expectNoPageHorizontalScroll(page);
});

test("accessible tabs, focus states, reduced motion, and axe scan", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 });
  await mockApi(page);
  await page.goto("/report/42");
  await page.getByRole("tab", { name: "Overview" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Billing" })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Warnings" })).toHaveAttribute("aria-selected", "true");

  const reducedMotionRule = await page.evaluate(() =>
    Array.from(document.styleSheets).some((sheet) =>
      Array.from(sheet.cssRules ?? []).some((rule) => rule.cssText.includes("prefers-reduced-motion")),
    ),
  );
  expect(reducedMotionRule).toBe(true);

  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const violations = await page.evaluate(async () => {
    // @ts-expect-error axe is injected by the test.
    const results = await window.axe.run(document);
    return results.violations.map((violation: { id: string; impact: string | null; nodes: unknown[] }) => ({
      id: violation.id,
      impact: violation.impact,
      nodes: violation.nodes.length,
    }));
  });
  expect(violations).toEqual([]);
});

test("authenticated hard refresh has no unexpected 401s and no duplicate region request", async ({ page }) => {
  const counts: ApiCounts = {};
  const statuses: number[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/")) statuses.push(response.status());
  });
  await mockApi(page, counts);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Run Analysis" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Run Analysis" })).toBeVisible();
  expect(statuses.filter((status) => status === 401)).toEqual([]);
  expect(counts["/api/regions"]).toBe(2);
  expect(counts["/api/aws/status"]).toBe(2);
});

test("routing and favicon smoke paths", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await page.goto("/signup");
  await expect(page.getByRole("heading", { name: "Create account" })).toBeVisible();

  await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Run Analysis" })).toBeVisible();
  await page.goto("/history");
  await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
  await page.goto("/report/42");
  await expect(page.getByRole("heading", { name: "BudgetBeagle Report" })).toBeVisible();
  await page.goto("/unknown-route");
  await expect(page.getByRole("heading", { name: "Run Analysis" })).toBeVisible();
  const favicon = await page.request.get("/favicon.svg");
  expect(favicon.status()).toBe(200);
});
