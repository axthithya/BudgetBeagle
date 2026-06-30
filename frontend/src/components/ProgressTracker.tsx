type ProgressTrackerProps = {
  messages: string[];
};

export function ProgressTracker({ messages }: ProgressTrackerProps) {
  if (!messages.length) {
    return (
      <div className="rounded-lg border border-dashed border-cloud-line bg-cloud-panel p-5 text-sm text-slate-400" role="status" aria-live="polite">
        No active run
      </div>
    );
  }

  return (
    <ol className="space-y-3 rounded-lg border border-cloud-line bg-cloud-panel p-5" role="status" aria-live="polite" aria-label="Analysis progress">
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
  );
}