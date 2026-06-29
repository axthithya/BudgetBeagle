import { useEffect, useMemo, useState } from "react";
import { Check, Copy, Loader2, Terminal } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { AnalysisRecord, AnalysisResult, Issue, apiFetch } from "../lib/api";

function isFullResult(value: AnalysisRecord["analysis_result"]): value is AnalysisResult {
  return Boolean((value as AnalysisResult).analysis);
}

export default function Report() {
  const { analysisId } = useParams();
  const [record, setRecord] = useState<AnalysisRecord | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;

    async function load() {
      if (!analysisId) return;
      try {
        const data = await apiFetch<{ analysis: AnalysisRecord }>(`/api/analyses/${analysisId}`);
        if (!active) return;
        setRecord(data.analysis);
        if (!["completed", "failed"].includes(data.analysis.status)) {
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
  const issues = result?.analysis.issues ?? [];

  async function copy(issue: Issue) {
    await navigator.clipboard.writeText(issue.fix_command);
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

  if (record.status !== "completed" || !result) {
    return <div className="flex items-center gap-3 text-slate-300"><Loader2 className="h-4 w-4 animate-spin" /> Analysis running</div>;
  }

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-white">Analysis Report</h1>
            <p className="mt-1 text-sm text-slate-400">{record.region} / {record.scan_target}</p>
          </div>
          <span className="rounded-md border border-cloud-green/50 px-3 py-1 text-sm text-emerald-200">Completed</span>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <Metric label="Resources" value={String(record.resources_scanned)} />
          <Metric label="Issues" value={String(record.issues_found)} />
          <Metric label="Savings" value={String(record.estimated_savings)} />
        </div>
        <p className="mt-5 text-sm leading-6 text-slate-300">{result.analysis.summary}</p>
      </section>

      {issues.length === 0 ? (
        <div className="rounded-lg border border-cloud-line bg-cloud-panel p-5 text-slate-300">No issues found</div>
      ) : (
        <section className="space-y-4">
          {issues.map((issue) => (
            <article key={`${issue.resource_id}-${issue.issue_type}`} className="rounded-lg border border-cloud-line bg-cloud-panel p-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-white">{issue.issue_type}</h2>
                  <p className="mt-1 break-all text-sm text-slate-400">{issue.resource_id}</p>
                </div>
                <Severity value={issue.severity} />
              </div>
              <p className="text-sm leading-6 text-slate-300">{issue.explanation}</p>
              <p className="mt-3 text-sm font-medium text-cloud-green">{String(issue.estimated_monthly_savings)}</p>
              <div className="mt-4 overflow-hidden rounded-lg border border-cloud-line bg-cloud-ink">
                <div className="flex items-center justify-between border-b border-cloud-line px-3 py-2">
                  <span className="inline-flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
                    <Terminal className="h-3.5 w-3.5" aria-hidden="true" /> aws cli
                  </span>
                  <button
                    type="button"
                    onClick={() => copy(issue)}
                    className="inline-flex h-8 items-center gap-2 rounded-md px-2 text-sm text-slate-300 hover:bg-slate-800 hover:text-white"
                  >
                    {copied === issue.resource_id ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                    {copied === issue.resource_id ? "Copied" : "Copy"}
                  </button>
                </div>
                <pre className="code-scroll overflow-x-auto p-3 text-sm text-slate-100"><code>{issue.fix_command}</code></pre>
              </div>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-cloud-line bg-cloud-ink p-4">
      <p className="text-xs font-semibold uppercase text-slate-500">{label}</p>
      <p className="mt-2 break-words text-xl font-semibold text-white">{value}</p>
    </div>
  );
}

function Severity({ value }: { value: string }) {
  const level = value.toLowerCase();
  const className = level === "high"
    ? "border-rose-400/50 bg-rose-500/10 text-rose-200"
    : level === "medium"
      ? "border-cloud-orange/50 bg-orange-500/10 text-orange-200"
      : "border-cloud-cyan/50 bg-teal-500/10 text-teal-200";
  return <span className={`rounded-md border px-3 py-1 text-sm capitalize ${className}`}>{value}</span>;
}