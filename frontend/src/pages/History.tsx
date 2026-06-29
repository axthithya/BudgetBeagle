import { useEffect, useState } from "react";
import { ChevronRight, Clock, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { AnalysisRecord, apiFetch } from "../lib/api";

export default function History() {
  const navigate = useNavigate();
  const [records, setRecords] = useState<AnalysisRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const data = await apiFetch<{ analyses: AnalysisRecord[] }>("/api/history");
        setRecords(data.analyses);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load history.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return <div className="flex items-center gap-3 text-slate-300"><Loader2 className="h-4 w-4 animate-spin" /> Loading history</div>;
  }

  if (error) {
    return <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-rose-100">{error}</div>;
  }

  return (
    <section className="rounded-lg border border-cloud-line bg-cloud-panel">
      <div className="border-b border-cloud-line p-5">
        <h1 className="text-2xl font-semibold text-white">History</h1>
      </div>
      {records.length === 0 ? (
        <p className="p-5 text-sm text-slate-400">No analyses yet</p>
      ) : (
        <div className="divide-y divide-cloud-line">
          {records.map((record) => (
            <button
              key={record.id}
              type="button"
              onClick={() => navigate(`/report/${record.id}`)}
              className="grid w-full gap-3 px-5 py-4 text-left hover:bg-slate-800/60 md:grid-cols-[1fr_120px_120px_120px_28px] md:items-center"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-white">{record.region} / {record.scan_target}</p>
                <p className="mt-1 flex items-center gap-2 text-sm text-slate-400">
                  <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                  {record.created_at ? new Date(record.created_at).toLocaleString() : "Queued"}
                </p>
              </div>
              <Pill value={record.status} />
              <span className="text-sm text-slate-300">{record.issues_found} issues</span>
              <span className="text-sm text-cloud-green">{record.estimated_savings}</span>
              <ChevronRight className="hidden h-5 w-5 text-slate-500 md:block" aria-hidden="true" />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function Pill({ value }: { value: string }) {
  const color = value === "completed"
    ? "border-emerald-400/50 text-emerald-200"
    : value === "failed"
      ? "border-rose-400/50 text-rose-200"
      : "border-cloud-orange/50 text-orange-200";
  return <span className={`w-fit rounded-md border px-2 py-1 text-xs font-semibold uppercase ${color}`}>{value}</span>;
}