export function formatMonthlySavings(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return `$${value.toFixed(2)}/month`;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed || trimmed.toLowerCase() === "unknown") return "Not enough data";
    const bareNumber = /^-?\d+(\.\d+)?$/.test(trimmed);
    if (bareNumber) {
      return `$${Number(trimmed).toFixed(2)}/month`;
    }
    return trimmed;
  }
  return "Not enough data";
}

export function formatStatus(value: string): string {
  if (value === "completed_with_warnings") return "Completed with warnings";
  if (value === "completed") return "Completed";
  if (value === "failed") return "Failed";
  if (value === "running") return "Running";
  if (value === "queued") return "Queued";
  return value;
}
