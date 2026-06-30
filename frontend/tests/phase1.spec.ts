import { expect, test } from "@playwright/test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

const mockRecord = {
  id: 42,
  user_id: 7,
  region: "us-east-1",
  scan_target: "whole-region",
  resources_scanned: 3,
  issues_found: 1,
  estimated_savings: "Not enough data",
  status: "completed_with_warnings",
  created_at: "2026-06-30T12:00:00Z",
  analysis_result: {
    schema_version: "2.0",
    report: {
      status: "completed_with_warnings",
      summary: "Responsive and accessibility proof report.",
      resources_scanned: 3,
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
      { service: "S3", id: "budgetbeagle-extremely-long-bucket-name-for-layout-proof-abcdefghijklmnopqrstuvwxyz", state: "active", type_or_sku: "bucket", metrics: { lifecycle_status: { status: "unknown" } } },
      { service: "EBS", id: "vol-0abcdef1234567890abcdef1234567890", state: "available", type_or_sku: "gp3", metrics: { size_gb: 8, unattached: true } },
    ],
    findings: [{
      id: "ebs:vol-0abc:test",
      category: "Confirmed issue",
      service: "EBS",
      resource_id: "vol-0abcdef1234567890abcdef1234567890",
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
      command: {
        text: "aws ec2 delete-volume --region us-east-1 --volume-id vol-0abcdef1234567890abcdef1234567890 --dry-run",
        risk: "destructive",
        risk_label: "Destructive",
        operation: "delete",
        valid: true,
      },
    }],
    warnings: [{ service: "S3", resource_id: "budgetbeagle-extremely-long-bucket-name-for-layout-proof-abcdefghijklmnopqrstuvwxyz", code: "AccessDenied", title: "S3 lifecycle configuration unavailable", message: "Lifecycle unknown", permission: "s3:GetLifecycleConfiguration", resolution: "Add optional read-only permission." }],
    billing: {
      status: "available",
      source: "AWS Cost Explorer",
      period: { label: "2026 YTD" },
      account_id: "****-****-2560",
      selected_region_label: "US East (N. Virginia)",
      account_total_ytd_usd: 123.45,
      selected_region_ytd_usd: 45.67,
      monthly_account_costs: [{ label: "Jun 2026", amount_usd: 45.67, display: "$45.67" }],
      service_costs_ytd: [{ name: "Amazon Elastic Compute Cloud", amount_usd: 45.67, display: "$45.67" }],
      region_costs_ytd: [{ name: "us-east-1", amount_usd: 45.67, display: "$45.67" }],
    },
    metrics: { account_total_ytd_display: "$123.45", selected_region_ytd_display: "$45.67" },
    scan_confidence: { score: 82, label: "High", level: "high", factors: [{ name: "Service scan coverage", effect: "positive", reason: "Resources scanned." }] },
    service_coverage: [{ service: "EC2", status: "completed", count: 1 }, { service: "S3", status: "completed_with_warnings", count: 1 }, { service: "EBS", status: "completed", count: 1 }],
    ai_enrichment: { status: "none", notes: [] },
  },
};

async function mockApi(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    localStorage.setItem("token", "test-token");
    localStorage.setItem("user", JSON.stringify({ id: 7, email: "phase1@example.com" }));
  });
  await page.route("**/api/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });
  await page.route("**/api/analyses/42", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ analysis: mockRecord }) });
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
  test(`responsive report viewport ${viewport.label}: no page overflow and readable sections`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await mockApi(page);
    await page.goto("/report/42");
    await expect(page.getByRole("heading", { name: "BudgetBeagle Report" })).toBeVisible();
    await expectNoPageHorizontalScroll(page);

    await page.getByRole("tab", { name: "Resources" }).click();
    const resourceId = page.getByText("budgetbeagle-extremely-long-bucket-name-for-layout-proof", { exact: false });
    await expect(resourceId.nth(viewport.width < 768 ? 1 : 0)).toBeVisible();
    await expectNoPageHorizontalScroll(page);

    await page.getByRole("tab", { name: "Commands" }).click();
    await expect(page.getByText("aws ec2 delete-volume", { exact: false })).toBeVisible();
    await expectNoPageHorizontalScroll(page);

    await page.getByRole("tab", { name: "Billing" }).click();
    await expect(page.getByRole("heading", { name: "Global Billing" })).toBeVisible();
    await expectNoPageHorizontalScroll(page);

    await page.getByRole("tab", { name: "Warnings" }).click();
    await expect(page.getByRole("heading", { name: "Scan completed with warnings" })).toBeVisible();
    await expect(page.getByText("s3:GetLifecycleConfiguration")).toBeVisible();
    await expectNoPageHorizontalScroll(page);
  });
}

test("accessible tabs, focus states, copy labels, reduced motion, and axe scan", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 });
  await mockApi(page);
  await page.goto("/report/42");
  await page.getByRole("tab", { name: "Overview" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Billing" })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Warnings" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("button", { name: /copy permission/i })).toBeVisible();

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
