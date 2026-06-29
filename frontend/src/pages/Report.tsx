import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  BarChart3,
  Check,
  ClipboardList,
  Copy,
  Database,
  Gauge,
  History,
  Layers,
  Loader2,
  Terminal,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { AnalysisRecord, AnalysisResult, BillingAmount, BillingContext, Issue, ScanWarning, apiFetch } from "../lib/api";
import { formatMonthlySavings, formatStatus } from "../lib/format";

function isFullResult(value: AnalysisRecord["analysis_result"]): value is AnalysisResult {
  return Boolean((value as AnalysisResult).analysis);
}

const TERMINAL_STATUSES = new Set(["completed", "completed_with_warnings", "failed"]);
type TabKey = "overview" | "billing" | "findings" | "resources" | "commands" | "warnings";

const tabs: { key: TabKey; label: string; icon: typeof BarChart3 }[] = [
  { key: "overview", label: "Overview", icon: Gauge },
  { key: "billing", label: "Billing", icon: BarChart3 },
  { key: "findings", label: "Findings", icon: ClipboardList },
  { key: "resources", label: "Resources", icon: Database },
  { key: "commands", label: "Commands", icon: Terminal },
  { key: "warnings", label: "Warnings", icon: AlertTriangle },
];

export default function Report() {
  const { analysisId } = useParams();
  const [record, setRecord] = useState<AnalysisRecord | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");

  useEffect(() => {
    let active = true;
    let timer: number | undefined;

    async function load() {
      if (!analysisId) return;
      try {
        const data = await apiFetch<{ analysis: AnalysisRecord }>(`/api/analyses/${analysisId}`);
        if (!active) return;
        setRecord(data.analysis);
        if (!TERMINAL_STATUSES.has(data.analysis.status)) {
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
  const findings = result?.analysis.findings ?? result?.analysis.issues ?? [];
  const warnings = result?.analysis.warnings ?? result?.scan.warnings ?? [];
  const billing = result?.analysis.billing ?? result?.scan.billing ?? {};
  const metrics = result?.analysis.metrics ?? {};
  const confidence = result?.analysis.confidence;
  const resources = result?.scan.resources ?? [];
  const commands = findings.filter((issue) => issue.command?.valid && issue.command.text);

  async function copy(issue: Issue) {
    const command = issue.command?.valid ? issue.command.text : issue.fix_command;
    if (!command) return;
    await navigator.clipboard.writeText(command);
    setCopied(issue.resource_id);
    window.setTimeout(() => setCopied(null), 1200);
  }

  if (error) {
    return <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-rose-100">{error}</div>;
  }

  if (!record) {
    return <div className="flex items-center gap-3 text-slate-300"><Loader2 className="h-4 w-4 animate-spin" /> Loading report</div>;
  }

  if (record.status === "failed") {
    const message = (record.analysis_result as { error?: string }).error ?? "Analysis failed.";
    return (
      <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-5 text-rose-100">
        <h1 className="text-xl font-semibold text-white">Analysis failed</h1>
        <p className="mt-2 text-sm">{message}</p>
        <Link className="mt-4 inline-block text-sm font-medium text-cloud-cyan" to="/">Back to dashboard</Link>
      </div>
    );
  }

  if (!TERMINAL_STATUSES.has(record.status) || !result) {
    return <div className="flex items-center gap-3 text-slate-300"><Loader2 className="h-4 w-4 animate-spin" /> Analysis running</div>;
  }

  const regionLabel = billing.selected_region_label ?? record.region;
  const period = billing.period?.label ?? "Current period";
  const scanDate = record.created_at ? new Date(record.created_at).toLocaleDateString() : "Queued";

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6 overflow-hidden">
      <header className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-normal text-white sm:text-3xl">Analysis Report</h1>
            <p className="mt-2 max-w-5xl break-words text-sm leading-6 text-slate-400">
              Region: {regionLabel} · Account {billing.account_id ?? result.scan.account_id ?? "Unknown"} · {period} · Scanned {scanDate}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge value={record.status} />
            <Link
              to="/history"
              className="inline-flex h-9 items-center gap-2 rounded-md border border-cloud-line px-3 text-sm text-slate-200 hover:border-cloud-cyan"
            >
              <History className="h-4 w-4" aria-hidden="true" />
              History
            </Link>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
          <Metric label="Account Total" sublabel="YTD global" value={metrics.account_total_ytd_display ?? formatMoney(billing.account_total_ytd_usd)} />
          <Metric label="Regional Spend" sublabel={record.region} value={metrics.selected_region_ytd_display ?? formatMoney(billing.selected_region_ytd_usd)} />
          <Metric label="Resources" sublabel="Scanned" value={String(record.resources_scanned)} />
          <Metric label="Optimizations" sublabel="Issue + review" value={String(metrics.unutilized_count ?? (result.analysis.confirmed_issues ?? record.issues_found) + (result.analysis.recommendations ?? 0))} tone="rose" />
          <Metric label="Confidence" sublabel={confidence?.label ?? metrics.confidence_label ?? "Derived"} value={`${confidence?.score ?? metrics.confidence_score ?? "--"}%`} />
          <Metric label="Monthly Savings" sublabel="Evidence-backed" value={metrics.monthly_savings_display ?? result.analysis.estimated_monthly_savings_display ?? formatMonthlySavings(record.estimated_savings)} tone="green" />
          <Metric label="Yearly Savings" sublabel="Annualized" value={metrics.yearly_savings_display ?? result.analysis.yearly_savings?.display ?? "Not enough data"} tone="green" />
        </div>
      </header>

      <nav className="flex gap-2 overflow-x-auto rounded-lg border border-cloud-line bg-cloud-panel p-2">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const selected = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-md px-3 text-sm font-medium transition ${
                selected ? "bg-cloud-cyan text-slate-950" : "text-slate-300 hover:bg-slate-800 hover:text-white"
              }`}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {tab.label}
            </button>
          );
        })}
      </nav>

      {activeTab === "overview" && (
        <OverviewTab result={result} billing={billing} warnings={warnings} confidence={confidence} findings={findings} />
      )}
      {activeTab === "billing" && <BillingTab billing={billing} />}
      {activeTab === "findings" && <FindingsTab findings={findings} copied={copied} onCopy={copy} />}
      {activeTab === "resources" && <ResourcesTab resources={resources} />}
      {activeTab === "commands" && <CommandsTab commands={commands} copied={copied} onCopy={copy} />}
      {activeTab === "warnings" && <WarningsTab warnings={warnings} />}
    </div>
  );
}

function OverviewTab({ result, billing, warnings, confidence, findings }: { result: AnalysisResult; billing: BillingContext; warnings: ScanWarning[]; confidence?: { score: number; label: string; basis?: string }; findings: Issue[] }) {
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

      <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
        <div className="flex items-center gap-2 text-white">
          <Layers className="h-5 w-5 text-cloud-cyan" aria-hidden="true" />
          <h2 className="text-lg font-semibold">Summary</h2>
        </div>
        <p className="mt-3 text-sm leading-7 text-slate-300">{result.analysis.summary}</p>
        {confidence && <p className="mt-3 text-sm text-slate-400">Confidence: {confidence.score}% · {confidence.basis}</p>}
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <MiniPanel title="Issue Mix" value={`${result.analysis.confirmed_issues ?? 0} issues`} detail={`${result.analysis.recommendations ?? 0} recommendations · ${result.analysis.observations ?? 0} observations`} />
        <MiniPanel title="Pricing Coverage" value={pricingCoverage(findings)} detail="Verified price sources only contribute numeric savings." />
        <MiniPanel title="Command Coverage" value={`${findings.filter((item) => item.command?.valid).length} commands`} detail="Commands appear only when backend evidence and constraints are valid." />
      </section>
    </div>
  );
}

function BillingTab({ billing }: { billing: BillingContext }) {
  const accountMonths = billing.monthly_account_costs ?? [];
  const serviceCosts = billing.service_costs_ytd ?? [];
  const regionCosts = billing.region_costs_ytd ?? [];

  if (billing.status !== "available") {
    return (
      <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5 text-slate-300">
        <h2 className="text-lg font-semibold text-white">Billing data unavailable</h2>
        <p className="mt-2 text-sm leading-6">{billing.error?.message ?? "Cost Explorer data was not available for this scan."}</p>
        {billing.error?.permission && <p className="mt-2 text-sm text-slate-400">Permission: {billing.error.permission}</p>}
      </section>
    );
  }

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
        <h2 className="text-lg font-semibold text-white">Global Billing</h2>
        <p className="mt-1 text-sm text-slate-400">{billing.period?.label ?? "YTD"} · {billing.source ?? "AWS Cost Explorer"}</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {accountMonths.map((month) => <MonthCard key={`${month.start}-${month.label}`} month={month} />)}
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <CostTable title="Service Costs" rows={serviceCosts} empty="No service cost rows returned." />
        <CostTable title="Billed Regions" rows={regionCosts} empty="No region cost rows returned." />
      </section>
    </div>
  );
}

function FindingsTab({ findings, copied, onCopy }: { findings: Issue[]; copied: string | null; onCopy: (issue: Issue) => void }) {
  if (!findings.length) {
    return <EmptyPanel title="No findings" detail="No confirmed issues, recommendations, or observations were produced for this scan." />;
  }
  return (
    <section className="space-y-4">
      {findings.map((issue) => (
        <FindingCard key={issue.id ?? `${issue.resource_id}-${issue.issue_type}`} issue={issue} copied={copied} onCopy={onCopy} />
      ))}
    </section>
  );
}

function ResourcesTab({ resources }: { resources: unknown[] }) {
  if (!resources.length) return <EmptyPanel title="No resources" detail="No resources were returned by the scan." />;
  return (
    <section className="overflow-hidden rounded-lg border border-cloud-line bg-cloud-panel">
      <div className="border-b border-cloud-line p-4">
        <h2 className="font-semibold text-white">Scanned Resources</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-cloud-ink text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">Service</th>
              <th className="px-4 py-3">Resource</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">State</th>
              <th className="px-4 py-3">Key Metrics</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-cloud-line">
            {resources.map((resource, index) => {
              const item = normalizeResource(resource);
              return (
                <tr key={`${item.id}-${index}`} className="align-top text-slate-300">
                  <td className="px-4 py-3 font-medium text-white">{item.service}</td>
                  <td className="max-w-[260px] break-words px-4 py-3">{item.id}</td>
                  <td className="px-4 py-3">{item.type}</td>
                  <td className="px-4 py-3">{item.state}</td>
                  <td className="max-w-[420px] break-words px-4 py-3 text-slate-400">{item.metrics}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CommandsTab({ commands, copied, onCopy }: { commands: Issue[]; copied: string | null; onCopy: (issue: Issue) => void }) {
  if (!commands.length) return <EmptyPanel title="No validated commands" detail="The backend did not produce any valid action commands for this report." />;
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

function WarningsTab({ warnings }: { warnings: ScanWarning[] }) {
  if (!warnings.length) return <EmptyPanel title="No scan warnings" detail="All requested checks completed without recorded warnings." />;
  return <WarningSummary warnings={warnings} expanded />;
}

function FindingCard({ issue, copied, onCopy }: { issue: Issue; copied: string | null; onCopy: (issue: Issue) => void }) {
  const savings = issue.estimated_monthly_savings_display ?? formatMonthlySavings(issue.estimated_monthly_savings);
  const maxAvoidable = issue.maximum_monthly_avoidable_cost_display;

  return (
    <article className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap gap-2">
            <Badge label={issue.category ?? "Recommendation"} tone="slate" />
            <Badge label={issue.severity} tone={severityTone(issue.severity)} />
            <Badge label={`${issue.confidence_score ?? confidencePercent(issue.confidence)}% confidence`} tone="green" />
          </div>
          <h2 className="mt-3 text-lg font-semibold text-white">{issue.issue_type}</h2>
          <p className="mt-1 break-all text-sm text-slate-400">{issue.service ?? "AWS"} / {issue.resource_id}</p>
        </div>
        <div className="text-left sm:text-right">
          <p className="text-sm text-slate-500">Savings</p>
          <p className="text-lg font-semibold text-cloud-green">{savings}</p>
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

function WarningSummary({ warnings, expanded = false }: { warnings: ScanWarning[]; expanded?: boolean }) {
  const visible = expanded ? warnings : warnings.slice(0, 3);
  return (
    <section className="rounded-lg border border-amber-400/40 bg-amber-500/10 p-5 text-amber-50">
      <div className="mb-3 flex items-center gap-2">
        <AlertTriangle className="h-5 w-5" aria-hidden="true" />
        <h2 className="font-semibold text-white">Scan completed with warnings</h2>
      </div>
      <div className="space-y-3">
        {visible.map((warning, index) => (
          <div key={`${warning.service}-${warning.resource_id ?? index}-${warning.code ?? index}`} className="text-sm leading-6">
            <p className="font-medium text-white">{warning.service}{warning.resource_id ? ` / ${warning.resource_id}` : ""}</p>
            <p>{warning.message}</p>
            {warning.permission && <p className="text-amber-100/80">Permission: {warning.permission}</p>}
          </div>
        ))}
      </div>
      {!expanded && warnings.length > visible.length && <p className="mt-3 text-sm text-amber-100/80">{warnings.length - visible.length} more warnings in the Warnings tab.</p>}
    </section>
  );
}

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
      <p className="mt-1 text-lg font-semibold text-white">{month.display}</p>
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
              <tr><th className="px-4 py-3">Name</th><th className="px-4 py-3">YTD Cost</th></tr>
            </thead>
            <tbody className="divide-y divide-cloud-line">
              {rows.map((row) => (
                <tr key={row.name ?? row.label}>
                  <td className="max-w-[420px] break-words px-4 py-3 font-medium text-slate-200">{row.name ?? row.label}</td>
                  <td className="px-4 py-3 font-semibold text-rose-200">{row.display}</td>
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
          <dt className="text-slate-500">{label}</dt>
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
        <button type="button" onClick={() => onCopy(issue)} className="inline-flex h-8 items-center gap-2 rounded-md px-2 text-sm text-slate-300 hover:bg-slate-800 hover:text-white">
          {copied === issue.resource_id ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copied === issue.resource_id ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="code-scroll overflow-x-auto p-3 text-sm text-slate-100"><code>{command}</code></pre>
    </div>
  );
}

function EmptyPanel({ title, detail }: { title: string; detail: string }) {
  return <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5"><h2 className="font-semibold text-white">{title}</h2><p className="mt-2 text-sm text-slate-400">{detail}</p></section>;
}

function Badge({ label, tone }: { label: string; tone: "slate" | "green" | "rose" | "amber" | "cyan" }) {
  const color = tone === "green" ? "border-emerald-400/40 bg-emerald-500/10 text-emerald-200" : tone === "rose" ? "border-rose-400/40 bg-rose-500/10 text-rose-200" : tone === "amber" ? "border-amber-400/40 bg-amber-500/10 text-amber-100" : tone === "cyan" ? "border-cloud-cyan/40 bg-cyan-500/10 text-cyan-100" : "border-cloud-line bg-slate-800/50 text-slate-300";
  return <span className={`rounded-md border px-2 py-1 text-xs font-semibold uppercase ${color}`}>{label}</span>;
}

function StatusBadge({ value }: { value: string }) {
  const className = value === "completed_with_warnings" ? "border-amber-400/50 bg-amber-500/10 text-amber-100" : value === "completed" ? "border-emerald-400/50 bg-emerald-500/10 text-emerald-200" : "border-rose-400/50 bg-rose-500/10 text-rose-200";
  return <span className={`rounded-md border px-3 py-1 text-sm ${className}`}>{formatStatus(value)}</span>;
}

function normalizeResource(resource: unknown) {
  const item = (resource && typeof resource === "object" ? resource : {}) as Record<string, unknown>;
  const metrics = item.metrics && typeof item.metrics === "object" ? item.metrics as Record<string, unknown> : {};
  const compactMetrics = Object.entries(metrics)
    .filter(([, value]) => value !== null && value !== undefined && typeof value !== "object")
    .slice(0, 5)
    .map(([key, value]) => `${key}: ${formatValue(value)}`)
    .join(" · ");
  return {
    service: String(item.service ?? "AWS"),
    id: String(item.id ?? "unknown"),
    type: String(item.type_or_sku ?? "-"),
    state: String(item.state ?? "-"),
    metrics: compactMetrics || "No scalar metrics",
  };
}

function pricingCoverage(findings: Issue[]) {
  if (!findings.length) return "No findings";
  const verified = findings.filter((item) => item.pricing_status === "verified" || item.pricing_source).length;
  return `${verified}/${findings.length} priced`;
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

function formatMoney(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return `$${value.toFixed(2)}`;
  if (typeof value === "string" && value.trim()) return value;
  return "Not enough data";
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Unknown";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}