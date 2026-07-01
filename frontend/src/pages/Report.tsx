import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import {
  AlertTriangle,
  BarChart3,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  Copy,
  Database,
  Download,
  Eye,
  EyeOff,
  Gauge,
  History,
  Info,
  Layers,
  Loader2,
  RefreshCcw,
  Shield,
  Terminal,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { AnalysisRecord, AnalysisResult, BillingAmount, BillingContext, Issue, ReportConfidence, ScanWarning, ServiceCoverage, RegionScanResult, apiFetch, apiFetchBlob } from "../lib/api";
import { isTerminalAnalysisStatus } from "../lib/analysisStatus";
import { formatMonthlySavings, formatStatus, formatMoney, formatDateTime, formatShortDate, formatDuration, humanLabel, humanizeMetricName, formatBytes } from "../lib/format";

function isFullResult(value: AnalysisRecord["analysis_result"]): value is AnalysisResult {
  return Boolean((value as AnalysisResult).report);
}
type TabKey = "overview" | "billing" | "findings" | "resources" | "commands" | "warnings";

const tabs: { key: TabKey; label: string; icon: typeof BarChart3 }[] = [
  { key: "overview", label: "Overview", icon: Gauge },
  { key: "billing", label: "Billing", icon: BarChart3 },
  { key: "findings", label: "Findings", icon: ClipboardList },
  { key: "resources", label: "Resources", icon: Database },
  { key: "commands", label: "Commands", icon: Terminal },
  { key: "warnings", label: "Warnings", icon: AlertTriangle },
];

// -- Schema version -----------------------------------------------------
const SCHEMA_VERSION = "2.1";

export default function Report() {
  const { analysisId } = useParams();
  const [record, setRecord] = useState<AnalysisRecord | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [showZeroBilling, setShowZeroBilling] = useState(false);
  const tabRefs = useRef<Partial<Record<TabKey, HTMLButtonElement | null>>>({});

  function selectTab(tab: TabKey) {
    setActiveTab(tab);
    window.requestAnimationFrame(() => tabRefs.current[tab]?.focus());
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, key: TabKey) {
    const currentIndex = tabs.findIndex((tab) => tab.key === key);
    const lastIndex = tabs.length - 1;
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight") nextIndex = currentIndex === lastIndex ? 0 : currentIndex + 1;
    else if (event.key === "ArrowLeft") nextIndex = currentIndex === 0 ? lastIndex : currentIndex - 1;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = lastIndex;
    else return;
    event.preventDefault();
    selectTab(tabs[nextIndex].key);
  }

  useEffect(() => {
    let active = true;
    let timer: number | undefined;

    async function load() {
      if (!analysisId) return;
      try {
        const data = await apiFetch<{ analysis: AnalysisRecord }>(`/api/analyses/${analysisId}`);
        if (!active) return;
        setRecord(data.analysis);
        if (!isTerminalAnalysisStatus(data.analysis.status)) {
          timer = window.setTimeout(load, 1800);
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Could not load report.");
      }
    }

    load();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [analysisId]);

  const result = useMemo(() => (record && isFullResult(record.analysis_result) ? record.analysis_result : null), [record]);
  const report = result?.report;
  const legacyScan = result?.scan;
  const findings = result?.findings ?? [];
  const warnings = result?.warnings ?? legacyScan?.warnings ?? [];
  const billing = result?.billing ?? legacyScan?.billing ?? {};
  const metrics = result?.metrics ?? {};
  const confidence = result?.scan_confidence;
  const resources = result?.resources ?? legacyScan?.resources ?? [];
  const commands = findings.filter((issue: Issue) => issue.command?.valid && issue.command.text);

  async function copy(issue: Issue) {
    const command = issue.command?.valid ? issue.command.text : issue.fix_command;
    if (!command) return;
    await navigator.clipboard.writeText(command);
    setCopied(issue.resource_id);
    window.setTimeout(() => setCopied(null), 1200);
  }

  async function copyText(text: string, id: string) {
    await navigator.clipboard.writeText(text);
    setCopied(id);
    window.setTimeout(() => setCopied(null), 1200);
  }

  function downloadJSON() {
    if (!result || !record) return;
    const exportData = {
      schema_version: SCHEMA_VERSION,
      exported_at: new Date().toISOString(),
      analysis_id: record.id,
      scanned_at: record.created_at,
      status: record.status,
      ...result,
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `budgetbeagle-report-${record.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function downloadCSV() {
    if (!record) return;
    try {
      const blob = await apiFetchBlob(`/api/analyses/${record.id}/export/zip`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `budgetbeagle_export_${record.id}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download export.");
    }
  }

  if (error) {
    return <div role="alert" className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-rose-100">{error}</div>;
  }

  if (!record) {
    return <div className="flex items-center gap-3 text-slate-300" aria-live="polite"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading report</div>;
  }

  if (record.status === "failed" || record.status === "cancelled" || record.status === "interrupted") {
    const message = (record.analysis_result as { error?: string }).error ?? `Analysis ${record.status}.`;
    return (
      <div role="alert" className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-5 text-rose-100">
        <h1 className="text-xl font-semibold text-white">Analysis {record.status}</h1>
        <p className="mt-2 text-sm">{message}</p>
        <Link className="mt-4 inline-block text-sm font-medium text-cloud-cyan" to="/">Run a new scan</Link>
      </div>
    );
  }

  if (!isTerminalAnalysisStatus(record.status) || !result || !report) {
    return <div className="flex items-center gap-3 text-slate-300" aria-live="polite"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Analysis running</div>;
  }

  const regionCount = result.resolved_regions?.length ?? 0;
  const regionLabel = billing.selected_region_label ?? (regionCount > 1 ? String(regionCount) + " selected scan regions" : record.region);
  const period = billing.period?.label ?? "Current period";
  const scanDate = record.created_at ? formatDateTime(record.created_at) : "Queued";

  const confirmedIssues = report.confirmed_issues ?? 0;
  const recommendations = report.recommendations ?? 0;
  const observations = report.observations ?? 0;
  const actionableCount = report.actionable_findings ?? confirmedIssues + recommendations;

  // Pricing coverage - only count actionable findings
  const actionableFindings = findings.filter((f) => canonicalCategory(f.category) !== "observation");
  const pricedCount = actionableFindings.filter((f) => f.pricing_status === "verified" || f.pricing_source).length;
  const pricingLabel = actionableFindings.length === 0 ? "Not applicable" : `${pricedCount}/${actionableFindings.length} priced`;
  const pricingDetail = actionableFindings.length === 0
    ? "No actionable findings require pricing data."
    : "Verified price sources only contribute numeric savings.";

  // Phase 1.11: Service scan coverage
  const coverage = normalizeCoverage(result.service_coverage, resources, warnings);
  const coverageStats = getCoverageSummary(coverage, resources.length, report.service_coverage_summary);
  const findingConfidence = summarizeFindingConfidence(findings);
  const savingsConfidence = report.savings_confidence;

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6 overflow-hidden">
      <header className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-normal text-white sm:text-3xl">BudgetBeagle Report</h1>
            <p className="mt-2 max-w-5xl break-words text-sm leading-6 text-slate-400">
              Region: {regionLabel}  -  Account {billing.account_id ?? result.scan.account_id ?? "Unknown"}  -  {period}  -  Scanned {scanDate}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge value={record.status} />
            <Link
              to="/"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-cloud-line px-3 text-sm text-slate-200 hover:border-cloud-cyan focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
            >
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              Scan again
            </Link>
            <button
              type="button"
              onClick={downloadJSON}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-cloud-line px-3 text-sm text-slate-200 hover:border-cloud-cyan focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
              aria-label="Download report as JSON"
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              JSON
            </button>
            <button
              type="button"
              onClick={downloadCSV}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-cloud-line px-3 text-sm text-slate-200 hover:border-cloud-cyan focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
              aria-label="Download report as CSV"
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              CSV
            </button>
            <Link
              to="/history"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-cloud-line px-3 text-sm text-slate-200 hover:border-cloud-cyan focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
            >
              <History className="h-4 w-4" aria-hidden="true" />
              History
            </Link>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
          <Metric label="Account Total" sublabel="YTD global" value={formatMoney(metrics.account_total_ytd_display ?? billing.account_total_ytd_usd)} />
          <Metric label="Regional Spend" sublabel={regionLabel} value={formatMoney(metrics.selected_region_ytd_display ?? billing.selected_region_ytd_usd)} />
          <Metric label="Regions" sublabel={result.region_mode ?? "single_region"} value={String(result.resolved_regions?.length ?? 1)} />
          <Metric label="Resources" sublabel="Discovered" value={String(coverageStats.resourcesDiscovered)} />
          <Metric label="Confirmed Issues" sublabel="confirmed_issue only" value={String(confirmedIssues)} tone={confirmedIssues > 0 ? "rose" : "slate"} />
          <Metric label="Recommendations" sublabel="Actionable review" value={String(recommendations)} tone={recommendations > 0 ? "rose" : "slate"} />
          <Metric label="Observations" sublabel="Not actionable" value={String(observations)} />
          <Metric label="Scan Confidence" sublabel={confidence?.label ?? metrics.confidence_label ?? "Derived"} value={confidence?.score != null ? `${confidence.score}%` : "Not applicable"} />
          <Metric label="Finding Confidence" sublabel={findingConfidence.detail} value={findingConfidence.value} />
          <Metric label="Savings Confidence" sublabel="Numeric savings only" value={formatConfidenceValue(savingsConfidence)} />
          <Metric label="Monthly Savings" sublabel="Evidence-backed" value={formatMoney(metrics.monthly_savings_display ?? report.estimated_monthly_savings_display ?? formatMonthlySavings(record.estimated_savings))} tone="green" />
        </div>
      </header>

      <nav className="flex gap-2 overflow-x-auto rounded-lg border border-cloud-line bg-cloud-panel p-2" role="tablist" aria-label="Report sections">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const selected = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              id={`tab-${tab.key}`}
              aria-selected={selected}
              aria-controls={`panel-${tab.key}`}
              ref={(node) => { tabRefs.current[tab.key] = node; }}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActiveTab(tab.key)}
              onKeyDown={(event) => handleTabKeyDown(event, tab.key)}
              className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-md px-3 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-cloud-cyan ${
                selected ? "bg-cloud-cyan text-slate-950" : "text-slate-300 hover:bg-slate-800 hover:text-white"
              }`}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {tab.label}
            </button>
          );
        })}
      </nav>

      <div role="tabpanel" id={`panel-${activeTab}`} aria-labelledby={`tab-${activeTab}`} tabIndex={0}>
        {activeTab === "overview" && (
          <OverviewTab result={result} billing={billing} warnings={warnings} confidence={confidence} savingsConfidence={savingsConfidence} findingConfidence={findingConfidence} coverage={coverage} coverageStats={coverageStats} confirmedIssues={confirmedIssues} recommendations={recommendations} observations={observations} actionableCount={actionableCount} pricingLabel={pricingLabel} pricingDetail={pricingDetail} />
        )}
        {activeTab === "billing" && <BillingTab billing={billing} showZero={showZeroBilling} onShowZeroChange={setShowZeroBilling} />}
        {activeTab === "findings" && <FindingsTab findings={findings} observations={observations} copied={copied} onCopy={copy} />}
        {activeTab === "resources" && <ResourcesTab resources={resources} copied={copied} onCopy={copyText} />}
        {activeTab === "commands" && <CommandsTab commands={commands} copied={copied} onCopy={copy} />}
        {activeTab === "warnings" && <WarningsTab warnings={warnings} copied={copied} onCopy={copyText} />}
      </div>
    </div>
  );
}

// -- Overview Tab --------------------------------------------------------

type OverviewProps = {
  result: AnalysisResult;
  billing: BillingContext;
  warnings: ScanWarning[];
  confidence?: ReportConfidence;
  savingsConfidence?: ReportConfidence;
  findingConfidence: FindingConfidenceSummary;
  coverage: CoverageEntry[];
  coverageStats: CoverageStats;
  confirmedIssues: number;
  recommendations: number;
  observations: number;
  actionableCount: number;
  pricingLabel: string;
  pricingDetail: string;
};

function OverviewTab({ result, billing, warnings, confidence, savingsConfidence, findingConfidence, coverage, coverageStats, confirmedIssues, recommendations, observations, actionableCount, pricingLabel, pricingDetail }: OverviewProps) {
  const summaryText = result.report.summary ?? "Report completed.";
  return (
    <div className="space-y-4">
      {(billing.insights ?? []).map((insight) => (
        <section key={insight.type} className="rounded-lg border border-amber-400/40 bg-amber-500/10 p-5 text-amber-50">
          <h2 className="font-semibold text-white">{insight.title}</h2>
          <p className="mt-2 text-sm leading-6">{insight.message}</p>
          {Boolean(insight.regions?.length) && (
            <div className="mt-4 flex flex-wrap gap-2">
              {insight.regions?.map((region) => <Badge key={region.name} label={`${region.name} ${region.display}`} tone="amber" />)}
            </div>
          )}
        </section>
      ))}

      {warnings.length > 0 && <WarningSummary warnings={warnings} />}
      {Boolean(result.regional_results?.length) && <RegionResultsSection regions={result.regional_results ?? []} />}

      <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
        <div className="flex items-center gap-2 text-white">
          <Layers className="h-5 w-5 text-cloud-cyan" aria-hidden="true" />
          <h2 className="text-lg font-semibold">Summary</h2>
        </div>
        <p className="mt-3 text-sm leading-7 text-slate-300">{summaryText}</p>
        <ConfidenceSection scanConfidence={confidence} findingConfidence={findingConfidence} savingsConfidence={savingsConfidence} />
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <MiniPanel
          title="Findings Breakdown"
          value={`${confirmedIssues} confirmed issue${confirmedIssues !== 1 ? "s" : ""}`}
          detail={`${recommendations} recommendation${recommendations !== 1 ? "s" : ""} - ${observations} observation${observations !== 1 ? "s" : ""} - ${actionableCount} actionable`}
        />
        <MiniPanel title="Pricing Coverage" value={pricingLabel} detail={pricingDetail} />
        <MiniPanel
          title="Service Coverage"
          value={`Services scanned: ${coverageStats.servicesScanned}/${coverageStats.totalServices}`}
          detail={`Services containing resources: ${coverageStats.servicesContainingResources}/${coverageStats.totalServices} - Resources discovered: ${coverageStats.resourcesDiscovered}`}
        />
      </section>

      {/* Phase 1.11: Scan coverage details */}
      <CoverageSection coverage={coverage} />
    </div>
  );
}

function RegionResultsSection({ regions }: { regions: RegionScanResult[] }) {
  const failed = regions.filter((item) => item.status === "failed").length;
  return (
    <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Regional Scan Results</h2>
          <p className="mt-1 text-sm text-slate-400">{regions.length} region{regions.length !== 1 ? "s" : ""} resolved - {failed} failed</p>
        </div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {regions.map((item) => (
          <div key={item.region} className="rounded-lg border border-cloud-line bg-cloud-ink p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="font-medium text-white">{item.region}</p>
              <StatusBadge value={item.status} />
            </div>
            <div className="mt-3 grid gap-1 text-sm text-slate-400">
              <span>Resources: {item.resources_discovered ?? 0}</span>
              <span>Findings: {item.findings_generated ?? 0}</span>
              <span>Warnings: {item.warning_count ?? item.warnings?.length ?? 0}</span>
            </div>
            {item.safe_error_message && <p className="mt-3 text-sm leading-6 text-amber-100">{item.safe_error_message}</p>}
          </div>
        ))}
      </div>
    </section>
  );
}
// -- Billing Tab --------------------------------------------------------

function BillingTab({ billing, showZero, onShowZeroChange }: { billing: BillingContext; showZero: boolean; onShowZeroChange: (value: boolean) => void }) {
  const accountMonths = billing.monthly_account_costs ?? [];
  const allServiceCosts = normalizeBillingRows(billing.service_costs_ytd ?? []);
  const allRegionCosts = normalizeBillingRows(billing.region_costs_ytd ?? []);
  const hasZeroRows = [...allServiceCosts, ...allRegionCosts].some(isZeroAmount);
  const nonZeroServices = allServiceCosts.filter((row) => !isZeroAmount(row));
  const nonZeroRegions = allRegionCosts.filter((row) => !isZeroAmount(row));
  const serviceCosts = showZero ? allServiceCosts : nonZeroServices;
  const regionCosts = showZero ? allRegionCosts : nonZeroRegions;

  if (billing.status !== "available") {
    return (
      <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5 text-slate-300">
        <h2 className="text-lg font-semibold text-white">Billing data unavailable</h2>
        <p className="mt-2 text-sm leading-6">{billing.error?.message ?? "Cost Explorer data was not available for this scan."}</p>
        {billing.error?.permission && <p className="mt-2 text-sm text-slate-400">Permission: <code className="text-slate-300">{billing.error.permission}</code></p>}
      </section>
    );
  }

  const allZero = nonZeroServices.length === 0 && nonZeroRegions.length === 0;

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-white">Global Billing</h2>
            <p className="mt-1 text-sm text-slate-400">{billing.period?.label ?? "YTD"} - {billing.source ?? "AWS Cost Explorer"}</p>
          </div>
          {hasZeroRows && (
            <button
              type="button"
              onClick={() => onShowZeroChange(!showZero)}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-cloud-line px-3 text-sm text-slate-300 hover:border-cloud-cyan focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
              aria-pressed={showZero}
            >
              {showZero ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
              {showZero ? "Hide zero-cost services" : "Show zero-cost services"}
            </button>
          )}
        </div>
        {hasZeroRows && (
          <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-400">
            Zero-cost entries can appear because AWS Cost Explorer reports service or regional usage dimensions even when the rounded billed amount is $0.00.
          </p>
        )}
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {accountMonths.map((month) => <MonthCard key={`${month.start}-${month.label}`} month={month} />)}
        </div>
      </section>

      {allZero && !showZero ? (
        <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
          <h2 className="font-semibold text-white">No billable usage detected for this period.</h2>
          <p className="mt-2 text-sm text-slate-400">All scanned services and regions show $0.00 spend. This does not mean resources were not scanned.</p>

        </section>
      ) : (
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <CostTable title="Service Costs" rows={serviceCosts} empty="No service cost rows returned." />
          <CostTable title="Billed Regions" rows={regionCosts} empty="No region cost rows returned." />
        </section>
      )}
    </div>
  );
}

// Findings Tab -------------------------------------------------------

function FindingsTab({ findings, observations, copied, onCopy }: { findings: Issue[]; observations: number; copied: string | null; onCopy: (issue: Issue) => void }) {
  if (!findings.length) {
    return (
      <EmptyPanel title="No confirmed cost issues were found.">
        {observations > 0 ? (
          <p className="mt-2 text-sm text-slate-400">
            {observations} observation{observations !== 1 ? "s" : ""} need{observations === 1 ? "s" : ""} more monitoring before BudgetBeagle can make a reliable recommendation.
          </p>
        ) : (
          <p className="mt-2 text-sm text-slate-400">All scanned resources appear to be configured appropriately based on available evidence.</p>
        )}
      </EmptyPanel>
    );
  }
  return (
    <section className="space-y-4">
      {findings.map((issue) => (
        <FindingCard key={issue.id ?? `${issue.resource_id}-${issue.issue_type}`} issue={issue} copied={copied} onCopy={onCopy} />
      ))}
    </section>
  );
}

// -- Resources Tab ------------------------------------------------------

function ResourcesTab({ resources, copied, onCopy }: { resources: unknown[]; copied: string | null; onCopy: (text: string, id: string) => void }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (!resources.length) return <EmptyPanel title="No resources">No resources were returned by the scan.</EmptyPanel>;

  return (
    <section className="space-y-0 overflow-hidden rounded-lg border border-cloud-line bg-cloud-panel">
      <div className="border-b border-cloud-line p-4">
        <h2 className="font-semibold text-white">Scanned Resources</h2>
      </div>
      {/* Desktop table */}
      <div className="hidden overflow-x-auto md:block">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-cloud-ink text-xs uppercase text-slate-500">
            <tr>
              <th scope="col" className="px-4 py-3">Service</th>
              <th scope="col" className="px-4 py-3">Resource</th>
              <th scope="col" className="px-4 py-3">Region</th>
              <th scope="col" className="px-4 py-3">Type</th>
              <th scope="col" className="px-4 py-3">State</th>
              <th scope="col" className="px-4 py-3">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-cloud-line">
            {resources.map((resource, index) => {
              const item = normalizeResource(resource);
              const isExpanded = expandedId === `${item.id}-${index}`;
              return (
                <tr key={`${item.id}-${index}`} className="align-top text-slate-300">
                  <td className="px-4 py-3 font-medium text-white">{item.service}</td>
                  <td className="max-w-[260px] px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="break-words">{item.id}</span>
                      <button
                        type="button"
                        onClick={() => onCopy(item.id, `res-${item.id}`)}
                        className="shrink-0 rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-white focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
                        aria-label={`Copy resource ID ${item.id}`}
                      >
                        {copied === `res-${item.id}` ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                      </button>
                    </div>
                  </td>
                  <td className="px-4 py-3">{item.type}</td>
                  <td className="px-4 py-3">{item.state}</td>
                  <td className="max-w-[420px] px-4 py-3">
                    <button
                      type="button"
                      onClick={() => setExpandedId(isExpanded ? null : `${item.id}-${index}`)}
                      className="inline-flex items-center gap-1 text-sm text-cloud-cyan hover:text-teal-200 focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
                      aria-expanded={isExpanded}
                    >
                      {isExpanded ? "Hide" : "View"} details
                      {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                    </button>
                    {isExpanded && (
                      <div className="mt-3 space-y-1.5">
                        {item.metricRows.map((row, i) => (
                          <div key={i} className="grid grid-cols-[140px_1fr] gap-2 text-sm">
                            <span className="text-slate-500">{row.label}</span>
                            <span className="text-slate-300">{row.value}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {/* Mobile cards */}
      <div className="divide-y divide-cloud-line md:hidden">
        {resources.map((resource, index) => {
          const item = normalizeResource(resource);
          const isExpanded = expandedId === `${item.id}-${index}`;
          return (
            <div key={`m-${item.id}-${index}`} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-medium text-white">{item.service}</p>
                  <div className="mt-1 flex items-center gap-2">
                    <p className="break-all text-sm text-slate-400">{item.id}</p>
                    <button
                      type="button"
                      onClick={() => onCopy(item.id, `res-m-${item.id}`)}
                      className="shrink-0 rounded p-1 text-slate-500 hover:text-white focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
                      aria-label={`Copy resource ID ${item.id}`}
                    >
                      {copied === `res-m-${item.id}` ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>
                <Badge label={item.state} tone="slate" />
              </div>
              <p className="mt-2 text-sm text-slate-400">Region: {item.region}</p>
              <p className="mt-1 text-sm text-slate-400">Type: {item.type}</p>
              <button
                type="button"
                onClick={() => setExpandedId(isExpanded ? null : `${item.id}-${index}`)}
                className="mt-2 text-sm text-cloud-cyan hover:text-teal-200 focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
                aria-expanded={isExpanded}
              >
                {isExpanded ? "Hide details" : "View details"}
              </button>
              {isExpanded && (
                <div className="mt-3 space-y-1.5">
                  {item.metricRows.map((row, i) => (
                    <div key={i} className="grid grid-cols-[120px_1fr] gap-2 text-sm">
                      <span className="text-slate-500">{row.label}</span>
                      <span className="text-slate-300">{row.value}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

// -- Commands Tab -------------------------------------------------------

function CommandsTab({ commands, copied, onCopy }: { commands: Issue[]; copied: string | null; onCopy: (issue: Issue) => void }) {
  if (!commands.length) {
    return (
      <EmptyPanel title="No safe actions are recommended yet.">
        <p className="mt-2 text-sm text-slate-400">BudgetBeagle only generates commands when evidence and service constraints are sufficient.</p>
      </EmptyPanel>
    );
  }
  return (
    <section className="space-y-4">
      {commands.map((issue) => (
        <article key={issue.id ?? `${issue.resource_id}-command`} className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold text-white">{issue.issue_type}</h2>
              <p className="mt-1 break-all text-sm text-slate-400">{issue.service} / {issue.resource_id}</p>
            </div>
            <Badge label={issue.command?.risk ?? "review"} tone={issue.command?.risk === "destructive" ? "rose" : "cyan"} />
          </div>
          {issue.action_risk && <p className="mt-3 text-sm text-slate-300">Risk: {issue.action_risk}</p>}
          <CommandBlock issue={issue} copied={copied} onCopy={onCopy} />
        </article>
      ))}
    </section>
  );
}

// -- Warnings Tab -------------------------------------------------------

function WarningsTab({ warnings, copied, onCopy }: { warnings: ScanWarning[]; copied: string | null; onCopy: (text: string, id: string) => void }) {
  if (!warnings.length) {
    return <EmptyPanel title="No scan warnings">All requested checks completed without recorded warnings.</EmptyPanel>;
  }
  return (
    <section className="space-y-4">
      <div className="flex items-center gap-2 text-amber-50">
        <AlertTriangle className="h-5 w-5" aria-hidden="true" />
        <h2 className="font-semibold text-white">Scan completed with warnings</h2>
      </div>
      {warnings.map((warning, index) => (
        <WarningCard key={`${warning.service}-${warning.resource_id ?? index}-${warning.code ?? index}`} warning={warning} copied={copied} onCopy={onCopy} />
      ))}
    </section>
  );
}

// -- Finding Card -------------------------------------------------------

function FindingCard({ issue, copied, onCopy }: { issue: Issue; copied: string | null; onCopy: (issue: Issue) => void }) {
  const savings = issue.estimated_monthly_savings_display ?? formatMonthlySavings(issue.estimated_monthly_savings);
  const maxAvoidable = issue.maximum_monthly_avoidable_cost_display;
  const findingConfidenceScore = issue.finding_confidence?.score ?? issue.confidence_score ?? confidencePercent(issue.confidence);
  const findingConfidenceLabel = issue.finding_confidence?.label ?? "Finding";
  const savingsConfidence = issue.savings_confidence;

  return (
    <article className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap gap-2">
            <Badge label={categoryLabel(issue.category)} tone="slate" />
            <Badge label={issue.severity} tone={severityTone(issue.severity)} />
            <Badge label={`${findingConfidenceLabel} ${findingConfidenceScore}% finding confidence`} tone="green" />
            {savingsConfidence && <Badge label={`${savingsConfidence.label} savings confidence`} tone="cyan" />}
          </div>
          <h2 className="mt-3 text-lg font-semibold text-white">{issue.issue_type}</h2>
          <p className="mt-1 break-all text-sm text-slate-400">{issue.region ?? issue.scope ?? "Unknown region"} / {issue.service ?? "AWS"} / {issue.resource_id}</p>
        </div>
        <div className="text-left sm:text-right">
          <p className="text-sm text-slate-500">Savings</p>
          <p className="text-lg font-semibold text-cloud-green">{savings}</p>
          {savings === "Not enough data" && (
            <p className="mt-1 max-w-[220px] text-xs text-slate-500">
              Savings confidence not applicable without numeric savings.
            </p>
          )}
        </div>
      </div>

      <p className="text-sm leading-6 text-slate-300">{issue.ai_explanation ?? issue.explanation}</p>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <Detail title="Evidence"><Evidence evidence={issue.evidence} /></Detail>
        <Detail title="Pricing"><p>{issue.pricing_source ?? issue.pricing_status ?? "Not available"}</p>{issue.pricing_basis && <p className="mt-2 text-slate-400">{issue.pricing_basis}</p>}</Detail>
        <Detail title="Basis"><p>{issue.savings_basis ?? "Not enough data"}</p>{maxAvoidable && maxAvoidable !== "Not enough data" && <p className="mt-2 text-slate-400">Maximum avoidable cost: {maxAvoidable}</p>}</Detail>
        <Detail title="Recommendation"><p>{issue.ai_recommendation ?? issue.recommendation ?? "Review before taking action."}</p>{issue.action_risk && <p className="mt-2 text-slate-400">Risk: {issue.action_risk}</p>}</Detail>
      </div>

      {issue.command?.valid && <CommandBlock issue={issue} copied={copied} onCopy={onCopy} />}
    </article>
  );
}

// -- Warning Summary + Card ---------------------------------------------

function WarningSummary({ warnings }: { warnings: ScanWarning[] }) {
  const visible = warnings.slice(0, 3);
  return (
    <section className="rounded-lg border border-amber-400/40 bg-amber-500/10 p-5 text-amber-50">
      <div className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-5 w-5" aria-hidden="true" />
        <h2 className="font-semibold text-white">Scan completed with warnings</h2>
      </div>
      <div className="space-y-2">
        {visible.map((warning, index) => (
          <p key={`${warning.service}-${warning.resource_id ?? index}-${warning.code ?? index}`} className="text-sm">
            <span className="font-medium text-white">{warning.title ?? warning.service}</span>
            {warning.resource_id ? ` - ${warning.resource_id}` : ""}
          </p>
        ))}
        {warnings.length > visible.length && (
          <p className="text-sm text-amber-100/80">{warnings.length - visible.length} more in the Warnings tab.</p>
        )}
      </div>
    </section>
  );
}

function WarningCard({ warning, copied, onCopy }: { warning: ScanWarning; copied: string | null; onCopy: (text: string, id: string) => void }) {
  const policySnippet = warning.permission && warning.resource_id
    ? JSON.stringify({
        Version: "2012-10-17",
        Statement: [{
          Sid: `BudgetBeagle${warning.service.replace(/\s/g, "")}Read`,
          Effect: "Allow",
          Action: warning.permission,
          Resource: warning.service === "S3" ? `arn:aws:s3:::${warning.resource_id}` : "*",
        }],
      }, null, 2)
    : null;

  return (
    <div className="rounded-lg border border-amber-400/20 bg-amber-500/5 p-4">
      <h3 className="font-semibold text-white">{warning.title ?? `${warning.service} check unavailable`}</h3>
      {warning.region && (
        <div className="mt-2 grid gap-1 text-sm sm:grid-cols-[140px_1fr]">
          <span className="text-amber-200/70">Region:</span>
          <span className="break-all text-white">{warning.region}</span>
        </div>
      )}
      {warning.resource_id && (
        <div className="mt-2 grid gap-1 text-sm sm:grid-cols-[140px_1fr]">
          <span className="text-amber-200/70">Resource:</span>
          <span className="break-all text-white">{warning.resource_id}</span>
        </div>
      )}
      {warning.permission && (
        <div className="mt-1 grid gap-1 text-sm sm:grid-cols-[140px_1fr]">
          <span className="text-amber-200/70">Missing permission:</span>
          <code className="break-all text-amber-200">{warning.permission}</code>
        </div>
      )}
      <div className="mt-1 grid gap-1 text-sm sm:grid-cols-[140px_1fr]">
        <span className="text-amber-200/70">Impact:</span>
        <span>{warning.message}</span>
      </div>
      {warning.resolution && (
        <div className="mt-1 grid gap-1 text-sm sm:grid-cols-[140px_1fr]">
          <span className="text-amber-200/70">Resolution:</span>
          <span>{warning.resolution}</span>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {warning.permission && (
          <button
            type="button"
            onClick={() => onCopy(warning.permission!, `perm-${warning.resource_id ?? warning.service}`)}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-amber-400/30 px-2.5 text-xs text-amber-100 hover:border-amber-300 focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
            aria-label={`Copy permission ${warning.permission}`}
          >
            {copied === `perm-${warning.resource_id ?? warning.service}` ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            Copy permission
          </button>
        )}
        {policySnippet && (
          <button
            type="button"
            onClick={() => onCopy(policySnippet, `policy-${warning.resource_id ?? warning.service}`)}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-amber-400/30 px-2.5 text-xs text-amber-100 hover:border-amber-300 focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
            aria-label="Copy IAM policy snippet"
          >
            {copied === `policy-${warning.resource_id ?? warning.service}` ? <Check className="h-3.5 w-3.5" /> : <Shield className="h-3.5 w-3.5" />}
            Copy IAM policy
          </button>
        )}
        <Link
          to="/"
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-amber-400/30 px-2.5 text-xs text-amber-100 hover:border-amber-300 focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
        >
          <RefreshCcw className="h-3.5 w-3.5" />
          Scan again
        </Link>
      </div>
      {policySnippet && (
        <p className="mt-2 text-xs text-amber-100/60">Review and attach this policy in the IAM console manually. BudgetBeagle never modifies IAM.</p>
      )}
    </div>
  );
}

// -- Confidence Section -------------------------------------------------

function ConfidenceSection({ scanConfidence, findingConfidence, savingsConfidence }: { scanConfidence?: ReportConfidence; findingConfidence: FindingConfidenceSummary; savingsConfidence?: ReportConfidence }) {
  const [open, setOpen] = useState(false);
  const factors = scanConfidence?.factors ?? [];
  return (
    <div className="mt-3 space-y-3">
      <div className="grid gap-3 md:grid-cols-3">
        <Detail title="Scan confidence"><p>{scanConfidence?.score != null ? `${scanConfidence.score}% - ${scanConfidence.label}` : "Not applicable"}</p></Detail>
        <Detail title="Finding confidence"><p>{findingConfidence.value}{findingConfidence.detail !== "Not applicable" ? ` - ${findingConfidence.detail}` : ""}</p></Detail>
        <Detail title="Savings confidence"><p>{formatConfidenceValue(savingsConfidence)}</p></Detail>
      </div>
      {scanConfidence && (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
          aria-expanded={open}
        >
          <Info className="h-4 w-4" aria-hidden="true" />
          Scan confidence details
          {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
      )}
      {open && factors.length > 0 && (
        <div className="space-y-2 rounded-lg border border-cloud-line bg-cloud-ink p-4">
          <p className="text-xs font-semibold uppercase text-slate-500">Scan confidence factors</p>
          {factors.map((factor, i) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              <span className={`mt-0.5 inline-block h-2 w-2 shrink-0 rounded-full ${factor.effect === "positive" ? "bg-emerald-400" : "bg-amber-400"}`} aria-hidden="true" />
              <div>
                <span className="font-medium text-slate-200">{factor.name}</span>
                <span className="text-slate-400"> - {factor.reason}</span>
              </div>
            </div>
          ))}
          {scanConfidence?.basis && <p className="mt-2 text-xs text-slate-500">{scanConfidence.basis}</p>}
        </div>
      )}
    </div>
  );
}

// Coverage Section ---------------------------------------------------

type CoverageEntry = {
  service: string;
  status: "completed" | "completed_with_warnings" | "no_resources" | "skipped" | "failed";
  count: number;
  label: string;
  scanned?: boolean;
  has_resources?: boolean;
};

type CoverageStats = {
  totalServices: number;
  servicesScanned: number;
  servicesContainingResources: number;
  resourcesDiscovered: number;
};

type FindingConfidenceSummary = {
  value: string;
  detail: string;
  score?: number;
};

function normalizeCoverage(coverage: ServiceCoverage[] | undefined, resources: unknown[], warnings: ScanWarning[]): CoverageEntry[] {
  if (!coverage?.length) return buildCoverage(resources, warnings);
  return coverage.map((entry) => ({
    service: entry.service,
    status: entry.status as CoverageEntry["status"],
    count: entry.count,
    label: entry.label ?? coverageLabel(entry.status, entry.count),
    scanned: entry.scanned ?? isScannedCoverageStatus(entry.status),
    has_resources: entry.has_resources ?? entry.count > 0,
  }));
}

function coverageLabel(status: string, count: number): string {
  if (status === "completed_with_warnings") return count > 0 ? `Completed with warnings - ${count} resource${count !== 1 ? "s" : ""}` : "Completed with warnings - no resources";
  if (status === "completed") return `Completed - ${count} resource${count !== 1 ? "s" : ""}`;
  if (status === "failed") return "Failed";
  if (status === "skipped") return "Skipped";
  return "Completed - no resources";
}

function buildCoverage(resources: unknown[], warnings: ScanWarning[]): CoverageEntry[] {
  const SUPPORTED_SERVICES = ["EC2", "EBS", "S3", "RDS", "Load Balancing", "Elastic IP", "NAT Gateway"];
  const countByService: Record<string, number> = {};
  resources.forEach((r) => {
    const item = (r && typeof r === "object" ? r : {}) as Record<string, unknown>;
    const svc = coverageServiceName(String(item.service ?? ""));
    if (svc) countByService[svc] = (countByService[svc] ?? 0) + 1;
  });
  const warnServices = new Set(warnings.map((w) => coverageServiceName(w.service)).filter(Boolean));

  return SUPPORTED_SERVICES.map((svc) => {
    const count = countByService[svc] ?? 0;
    const hasWarning = warnServices.has(svc);
    let status: CoverageEntry["status"];
    if (hasWarning) status = "completed_with_warnings";
    else if (count > 0) status = "completed";
    else status = "no_resources";
    return { service: svc, status, count, label: coverageLabel(status, count), scanned: isScannedCoverageStatus(status), has_resources: count > 0 };
  });
}

function CoverageSection({ coverage }: { coverage: CoverageEntry[] }) {
  return (
    <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
      <h2 className="font-semibold text-white">Service Scan Coverage</h2>
      <div className="mt-3 space-y-2">
        {coverage.map((entry) => (
          <div key={entry.service} className="flex items-center gap-3 text-sm">
            <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${
              entry.status === "completed" ? "bg-emerald-400" :
              entry.status === "completed_with_warnings" ? "bg-amber-400" :
              entry.status === "no_resources" ? "bg-slate-500" :
              entry.status === "failed" ? "bg-rose-400" : "bg-slate-600"
            }`} aria-hidden="true" />
            <span className="font-medium text-slate-200">{entry.service}:</span>
            <span className="text-slate-400">{entry.label}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

// -- Shared Components --------------------------------------------------

function Metric({ label, sublabel, value, tone = "slate" }: { label: string; sublabel: string; value: string; tone?: "slate" | "green" | "rose" }) {
  const color = tone === "green" ? "border-emerald-500/30 bg-emerald-500/10 text-cloud-green" : tone === "rose" ? "border-rose-500/30 bg-rose-500/10 text-rose-200" : "border-cloud-line bg-cloud-panel text-white";
  return (
    <div className={`min-h-[116px] rounded-lg border p-4 ${color}`}>
      <p className="text-xs font-semibold uppercase text-slate-500">{label}</p>
      <p className="mt-1 min-h-5 text-xs text-slate-500">{sublabel}</p>
      <p className="mt-3 break-words text-2xl font-semibold leading-tight">{value}</p>
    </div>
  );
}

function MiniPanel({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
      <p className="text-xs font-semibold uppercase text-slate-500">{title}</p>
      <p className="mt-2 text-xl font-semibold text-white">{value}</p>
      <p className="mt-2 text-sm leading-6 text-slate-400">{detail}</p>
    </section>
  );
}

function Detail({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-cloud-line bg-cloud-ink p-4 text-sm text-slate-300">
      <p className="mb-2 text-xs font-semibold uppercase text-slate-500">{title}</p>
      {children}
    </div>
  );
}

function MonthCard({ month }: { month: BillingAmount }) {
  return (
    <div className="rounded-lg border border-cloud-line bg-cloud-ink p-3">
      <p className="text-xs text-slate-500">{month.label}</p>
      <p className="mt-1 text-lg font-semibold text-white">{formatMoney(month.display ?? month.amount_usd)}</p>
    </div>
  );
}

function CostTable({ title, rows, empty }: { title: string; rows: BillingAmount[]; empty: string }) {
  return (
    <section className="overflow-hidden rounded-lg border border-cloud-line bg-cloud-panel">
      <div className="border-b border-cloud-line p-4">
        <h2 className="font-semibold text-white">{title}</h2>
      </div>
      {rows.length === 0 ? (
        <p className="p-4 text-sm text-slate-400">{empty}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-cloud-ink text-xs uppercase text-slate-500">
              <tr><th scope="col" className="px-4 py-3">Name</th><th scope="col" className="px-4 py-3">YTD Cost</th></tr>
            </thead>
            <tbody className="divide-y divide-cloud-line">
              {rows.map((row) => (
                <tr key={row.name ?? row.label}>
                  <td className="max-w-[420px] break-words px-4 py-3 font-medium text-slate-200">{billingName(row)}</td>
                  <td className="px-4 py-3 font-semibold text-rose-200">{formatMoney(row.display ?? row.amount_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Evidence({ evidence }: { evidence?: Record<string, unknown> }) {
  const entries = Object.entries(evidence ?? {});
  if (!entries.length) return <p>Not enough data</p>;
  return (
    <dl className="space-y-2">
      {entries.map(([label, value]) => (
        <div key={label} className="grid gap-1 sm:grid-cols-[170px_1fr]">
          <dt className="text-slate-500">{humanizeMetricName(label)}</dt>
          <dd className="break-words text-slate-200">{formatValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function CommandBlock({ issue, copied, onCopy }: { issue: Issue; copied: string | null; onCopy: (issue: Issue) => void }) {
  const command = issue.command?.valid ? issue.command.text : "";
  if (!command) return null;
  return (
    <div className="mt-4 overflow-hidden rounded-lg border border-cloud-line bg-cloud-ink">
      <div className="flex items-center justify-between border-b border-cloud-line px-3 py-2">
        <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase text-slate-400"><Terminal className="h-3.5 w-3.5" aria-hidden="true" /> aws cli</span>
        <button
          type="button"
          onClick={() => onCopy(issue)}
          className="inline-flex h-8 items-center gap-2 rounded-md px-2 text-sm text-slate-300 hover:bg-slate-800 hover:text-white focus:outline-none focus:ring-2 focus:ring-cloud-cyan"
          aria-label="Copy command to clipboard"
        >
          {copied === issue.resource_id ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copied === issue.resource_id ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="code-scroll overflow-x-auto p-3 text-sm text-slate-100"><code>{command}</code></pre>
    </div>
  );
}

function EmptyPanel({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
      <h2 className="font-semibold text-white">{title}</h2>
      {children ?? <p className="mt-2 text-sm text-slate-400">No items available.</p>}
    </section>
  );
}

function Badge({ label, tone }: { label: string; tone: "slate" | "green" | "rose" | "amber" | "cyan" }) {
  const color = tone === "green" ? "border-emerald-400/40 bg-emerald-500/10 text-emerald-200" : tone === "rose" ? "border-rose-400/40 bg-rose-500/10 text-rose-200" : tone === "amber" ? "border-amber-400/40 bg-amber-500/10 text-amber-100" : tone === "cyan" ? "border-cloud-cyan/40 bg-cyan-500/10 text-cyan-100" : "border-cloud-line bg-slate-800/50 text-slate-300";
  return <span className={`rounded-md border px-2 py-1 text-xs font-semibold uppercase ${color}`}>{label}</span>;
}

function StatusBadge({ value }: { value: string }) {
  const className = value === "completed_with_warnings" ? "border-amber-400/50 bg-amber-500/10 text-amber-100"
    : value === "completed" ? "border-emerald-400/50 bg-emerald-500/10 text-emerald-200"
    : value === "cancelled" ? "border-slate-400/50 bg-slate-500/10 text-slate-300"
    : "border-rose-400/50 bg-rose-500/10 text-rose-200";
  return <span className={`rounded-md border px-3 py-1 text-sm ${className}`}>{formatStatus(value)}</span>;
}

// -- Normalization & Formatting -----------------------------------------

type MetricRow = { label: string; value: string };

function canonicalCategory(value?: string): "confirmed_issue" | "recommendation" | "observation" {
  const normalized = String(value ?? "recommendation").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (["confirmed_issue", "confirmed_issues", "confirmedissue", "issue", "issues"].includes(normalized)) return "confirmed_issue";
  if (["observation", "observations"].includes(normalized)) return "observation";
  return "recommendation";
}

function categoryLabel(value?: string): string {
  const category = canonicalCategory(value);
  if (category === "confirmed_issue") return "Confirmed issue";
  if (category === "observation") return "Observation";
  return "Recommendation";
}

function formatConfidenceValue(confidence?: ReportConfidence): string {
  if (!confidence || confidence.level === "not_applicable" || confidence.label === "Not applicable") return "Not applicable";
  return confidence.score != null ? `${confidence.score}% - ${confidence.label}` : confidence.label;
}

function summarizeFindingConfidence(findings: Issue[]): FindingConfidenceSummary {
  const scores = findings
    .map((issue) => issue.finding_confidence?.score ?? issue.confidence_score ?? confidencePercent(issue.confidence))
    .filter((score): score is number => Number.isFinite(score));
  if (!scores.length) return { value: "Not applicable", detail: "Not applicable" };
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const average = Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length);
  const label = average >= 80 ? "High" : average >= 65 ? "Medium" : "Low";
  if (min !== max) return { value: `${min}-${max}%`, detail: "range", score: average };
  return { value: `${average}%`, detail: `${label} average`, score: average };
}

function getCoverageSummary(coverage: CoverageEntry[], resourceCount: number, summary?: { total_supported_services?: number; services_scanned?: number; services_containing_resources?: number; resources_discovered?: number }): CoverageStats {
  const totalServices = summary?.total_supported_services ?? coverage.length;
  const servicesScanned = summary?.services_scanned ?? coverage.filter((entry) => entry.scanned ?? isScannedCoverageStatus(entry.status)).length;
  const servicesContainingResources = summary?.services_containing_resources ?? coverage.filter((entry) => (entry.scanned ?? isScannedCoverageStatus(entry.status)) && entry.count > 0).length;
  const resourcesDiscovered = summary?.resources_discovered ?? (coverage.reduce((sum, entry) => sum + entry.count, 0) || resourceCount);
  return { totalServices, servicesScanned, servicesContainingResources, resourcesDiscovered };
}

function isScannedCoverageStatus(status: string): boolean {
  return ["completed", "completed_with_warnings", "no_resources"].includes(status);
}

function coverageServiceName(service: string): string {
  const normalized = service.toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (["ELB", "ELBV2", "CLASSICELB", "LOADBALANCING"].includes(normalized)) return "Load Balancing";
  if (["ELASTICIP", "EIP"].includes(normalized)) return "Elastic IP";
  if (normalized === "NATGATEWAY") return "NAT Gateway";
  if (["EC2", "EBS", "S3", "RDS"].includes(normalized)) return normalized;
  return "";
}

function normalizeBillingRows(rows: BillingAmount[]): BillingAmount[] {
  return [...rows].sort((a, b) => {
    const amountA = billingAmountValue(a);
    const amountB = billingAmountValue(b);
    const zeroA = Math.abs(amountA) < 0.005;
    const zeroB = Math.abs(amountB) < 0.005;
    if (zeroA !== zeroB) return zeroA ? 1 : -1;
    if (!zeroA && amountA !== amountB) return amountB - amountA;
    return billingName(a).localeCompare(billingName(b));
  });
}

function billingAmountValue(row: BillingAmount): number {
  const raw = row.amount_usd ?? row.display ?? 0;
  const value = typeof raw === "number" ? raw : Number(String(raw).replace(/[^0-9.-]/g, ""));
  return Number.isFinite(value) ? value : 0;
}

function isZeroAmount(row: BillingAmount): boolean {
  return Math.abs(billingAmountValue(row)) < 0.005;
}

function billingName(row: BillingAmount): string {
  const name = row.name ?? row.label ?? "";
  if (!name || name === "NoRegion") return "Global / No Region";
  return name;
}

function normalizeResource(resource: unknown) {
  const item = (resource && typeof resource === "object" ? resource : {}) as Record<string, unknown>;
  const metrics = item.metrics && typeof item.metrics === "object" ? item.metrics as Record<string, unknown> : {};
  const service = String(item.service ?? "AWS").toUpperCase();
  const metricRows: MetricRow[] = [];

  if (service === "EC2") {
    const cpu = metrics.cpu_utilization as Record<string, unknown> | undefined;
    const avgCpu = cpu?.average ?? metrics.avg_cpu_14d;
    const dpCount = cpu?.datapoint_count ?? (avgCpu != null ? "?" : 0);
    const duration = cpu?.actual_duration_hours;
    const launchTime = formatShortDate(cpu?.instance_launch_time ?? metrics.launch_time);
    const assessment = Number(dpCount) < 24 && avgCpu != null
      ? "More monitoring required"
      : avgCpu != null && Number(dpCount) > 0 && Number(avgCpu) < 10 ? "Review candidate" : avgCpu == null ? "No data" : "Normal utilization";
    metricRows.push({ label: "Type", value: String(item.type_or_sku ?? "-") });
    metricRows.push({ label: "State", value: String(item.state ?? "-") });
    metricRows.push({ label: "Launch time", value: launchTime });
    metricRows.push({ label: "Average CPU", value: fmtPct(avgCpu) });
    metricRows.push({ label: "Datapoints", value: String(dpCount) });
    if (duration != null) metricRows.push({ label: "Observed duration", value: formatDuration(duration) });
    metricRows.push({ label: "Assessment", value: assessment });
  } else if (service === "EBS") {
    const iops = metrics.iops;
    const throughput = metrics.throughput_mibps ?? metrics.throughput;
    const size = metrics.size_gb;
    const attachCount = metrics.attachment_count ?? (metrics.unattached ? 0 : "?");
    const isGp3 = String(item.type_or_sku ?? "").toLowerCase() === "gp3";
    const iopsLabel = isGp3 && (iops === 3000 || iops == null) ? "3,000 - included baseline" : iops != null ? String(iops) : "Unknown";
    const tpLabel = isGp3 && (throughput === 125 || throughput == null) ? "125 MiB/s - included baseline" : throughput != null ? `${throughput} MiB/s` : "Unknown";
    const assessment = metrics.unattached ? "Unattached - review for deletion" : "Normal configuration";
    metricRows.push({ label: "Type", value: String(item.type_or_sku ?? "-") });
    metricRows.push({ label: "Size", value: size != null ? `${size} GiB` : "Unknown" });
    metricRows.push({ label: "State", value: String(item.state ?? "-") });
    metricRows.push({ label: "IOPS", value: iopsLabel });
    metricRows.push({ label: "Throughput", value: tpLabel });
    metricRows.push({ label: "Attachments", value: String(attachCount) });
    metricRows.push({ label: "Assessment", value: assessment });
  } else if (service === "S3") {
    const lifecycle = metrics.lifecycle_status as Record<string, unknown> | undefined;
    let lcStatus = "Unknown";
    let lcReason = "";
    if (lifecycle && typeof lifecycle === "object") {
      const st = String(lifecycle.status ?? "unknown").toLowerCase();
      if (st === "present") lcStatus = "Configured";
      else if (st === "absent") lcStatus = "Not configured";
      else { lcStatus = "Unknown"; lcReason = lifecycle.code === "AccessDenied" ? "Permission denied" : String(lifecycle.message ?? "Could not verify"); }
    } else if (typeof metrics.lifecycle_status === "string") {
      const st = metrics.lifecycle_status as string;
      if (st === "present") lcStatus = "Configured";
      else if (st === "absent") lcStatus = "Not configured";
      else lcStatus = "Unknown";
    }
    const sizeBytes = metrics.bucket_size_bytes;
    metricRows.push({ label: "State", value: "Active" });
    metricRows.push({ label: "Lifecycle policy", value: lcStatus });
    if (lcReason) metricRows.push({ label: "Reason", value: lcReason });
    metricRows.push({ label: "Current size", value: sizeBytes != null ? formatBytes(sizeBytes) : "No data" });
    metricRows.push({ label: "Assessment", value: lcStatus === "Unknown" ? "Could not fully inspect" : lcStatus === "Not configured" ? "Review lifecycle policy" : "Normal" });
  } else {
    const entries = Object.entries(metrics)
      .filter(([, value]) => value !== null && value !== undefined && typeof value !== "object")
      .slice(0, 5);
    entries.forEach(([key, value]) => {
      metricRows.push({ label: humanLabel(key), value: formatValue(value) });
    });
    if (metricRows.length === 0) metricRows.push({ label: "Metrics", value: "No scalar metrics" });
  }

  return {
    service: String(item.service ?? "AWS"),
    id: String(item.id ?? "unknown"),
    region: String(item.region ?? item.scope ?? "Unknown"),
    type: String(item.type_or_sku ?? "-"),
    state: String(item.state ?? "-"),
    metricRows,
    metrics: metricRows.map((r) => `${r.label}: ${r.value}`).join("  -  "),
  };
}

function confidencePercent(value?: string) {
  if (value === "high") return 90;
  if (value === "medium") return 75;
  return 55;
}

function severityTone(value: string): "green" | "rose" | "amber" | "cyan" {
  const level = value.toLowerCase();
  if (level === "high") return "rose";
  if (level === "medium") return "amber";
  if (level === "low") return "green";
  return "cyan";
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Unknown";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  // Try to detect and format ISO timestamps
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return formatDateTime(value);
  return String(value);
}

function fmtPct(value: unknown): string {
  if (value == null) return "No data";
  const num = Number(value);
  return Number.isFinite(num) ? `${num.toFixed(2)}%` : "No data";
}

function csvRow(values: string[]): string {
  return values.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",");
}
