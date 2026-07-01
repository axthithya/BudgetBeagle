type ProgressDetails = {
  region_mode?: string;
  total_region_count?: number;
  completed_region_count?: number;
  failed_region_count?: number;
  active_regions?: string[];
  current_service?: string;
  resources_discovered?: number;
  findings_generated?: number;
  warning_count?: number;
  cancellation_state?: string;
  overall_percentage?: number;
};

type ProgressTrackerProps = {
  messages: string[];
  details?: ProgressDetails | null;
};

export function ProgressTracker({ messages, details }: ProgressTrackerProps) {
  if (!messages.length) {
    return (
      <div className="rounded-lg border border-dashed border-cloud-line bg-cloud-panel p-5 text-sm text-slate-400" role="status" aria-live="polite">
        No active run
      </div>
    );
  }

  const percent = clampPercent(details?.overall_percentage);
  const total = details?.total_region_count ?? 0;
  const completed = details?.completed_region_count ?? 0;
  const failed = details?.failed_region_count ?? 0;
  const active = details?.active_regions ?? [];

  return (
    <div className="space-y-3 rounded-lg border border-cloud-line bg-cloud-panel p-5" role="status" aria-live="polite" aria-label="Analysis progress">
      {details && (
        <div className="space-y-3">
          <div>
            <div className="flex items-center justify-between gap-3 text-xs text-slate-400">
              <span>{details.region_mode ? labelMode(details.region_mode) : "Scan progress"}</span>
              <span>Overall progress: {percent}%</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-cloud-ink" aria-hidden="true">
              <div className="h-full rounded-full bg-cloud-cyan transition-all" style={{ width: `${percent}%` }} />
            </div>
          </div>
          {total > 0 && (
            <div className="grid gap-2 text-xs text-slate-300 sm:grid-cols-3">
              <span>Regions: {completed + failed}/{total}</span>
              <span>Failed: {failed}</span>
              <span>Warnings: {details.warning_count ?? 0}</span>
            </div>
          )}
          {active.length > 0 && <p className="break-words text-xs text-slate-400">Active: {active.join(", ")}</p>}
          {details.current_service && <p className="text-xs text-slate-400">Service: {details.current_service}</p>}
        </div>
      )}

      <ol className="space-y-3">
        {messages.map((message, index) => {
          const isLatest = index === messages.length - 1;
          return (
            <li key={`${message}-${index}`} className="flex items-start gap-3 text-sm">
              <span
                aria-hidden="true"
                className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${
                  isLatest ? "animate-pulse bg-cloud-orange" : "bg-cloud-green"
                }`}
              />
              <span className={isLatest ? "text-white" : "text-slate-300"}>{message}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function clampPercent(value: unknown) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

function labelMode(value: string) {
  if (value === "selected_regions") return "Selected regions";
  if (value === "all_enabled_regions") return "All enabled regions";
  return "Single region";
}