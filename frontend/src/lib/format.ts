/**
 * Shared formatting utilities for BudgetBeagle frontend.
 * All currency, date, duration, and status formatting lives here.
 */

// ── Currency ──────────────────────────────────────────────────────────

/** Format a USD amount to 2 decimal places. Normalizes negative-zero. */
export function formatUSD(value: unknown): string {
  if (value === null || value === undefined) return "Not enough data";
  const num = typeof value === "string" ? Number(value) : value;
  if (typeof num !== "number" || !Number.isFinite(num)) return "Not enough data";
  // Normalize -0 and values very close to zero
  const safe = Math.abs(num) < 0.005 ? 0 : num;
  return `$${(safe === 0 ? 0 : safe).toFixed(2)}`;
}

/** Format monthly savings — returns "$X.XX/month" or "Not enough data". */
export function formatMonthlySavings(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    const safe = Math.abs(value) < 0.005 ? 0 : value;
    return `$${(safe === 0 ? 0 : safe).toFixed(2)}/month`;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed || trimmed.toLowerCase() === "unknown") return "Not enough data";
    const bareNumber = /^-?\d+(\.\d+)?$/.test(trimmed);
    if (bareNumber) {
      const num = Number(trimmed);
      const safe = Math.abs(num) < 0.005 ? 0 : num;
      return `$${(safe === 0 ? 0 : safe).toFixed(2)}/month`;
    }
    return trimmed;
  }
  return "Not enough data";
}

/** Format a USD value for display, with "Not enough data" fallback. */
export function formatMoney(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return formatUSD(value);
  if (typeof value === "string" && value.trim()) return value;
  return "Not enough data";
}

// ── Status ────────────────────────────────────────────────────────────

export function formatStatus(value: string): string {
  const map: Record<string, string> = {
    completed_with_warnings: "Completed with warnings",
    completed: "Completed",
    failed: "Failed",
    running: "Running",
    queued: "Queued",
    cancelled: "Cancelled",
    interrupted: "Interrupted",
  };
  return map[value] ?? value;
}

// ── Dates & Times ─────────────────────────────────────────────────────

/** Format an ISO timestamp to a human-readable local date+time with timezone. */
export function formatDateTime(value: unknown): string {
  if (!value) return "Unknown";
  try {
    const d = new Date(String(value));
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    });
  } catch {
    return String(value);
  }
}

/** Format an ISO timestamp to a short date. */
export function formatShortDate(value: unknown): string {
  if (!value) return "Unknown";
  try {
    const d = new Date(String(value));
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return String(value);
  }
}

/** Format a duration in hours to a human-readable string. */
export function formatDuration(hours: unknown): string {
  if (hours == null) return "Unknown";
  const num = Number(hours);
  if (!Number.isFinite(num) || num < 0) return "Unknown";
  if (num < 1) return "less than 1 hour";
  if (num < 24) return `${num.toFixed(1)} hours`;
  const days = Math.floor(num / 24);
  const remaining = Math.round(num % 24);
  if (remaining === 0) return days === 1 ? "1 day" : `${days} days`;
  return `${days} day${days > 1 ? "s" : ""}, ${remaining} hour${remaining > 1 ? "s" : ""}`;
}

// ── Metric Labels ─────────────────────────────────────────────────────

/** Convert CloudWatch-style metric names to human-readable labels. */
export function humanizeMetricName(name: string): string {
  const map: Record<string, string> = {
    CPUUtilization: "CPU utilization",
    NetworkIn: "Network in",
    NetworkOut: "Network out",
    DiskReadOps: "Disk read ops",
    DiskWriteOps: "Disk write ops",
    StatusCheckFailed: "Status check failed",
  };
  if (map[name]) return map[name];
  // Generic: insert spaces before capitals and lowercase
  return name
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .replace(/^./, (c) => c.toUpperCase());
}

/** Convert snake_case keys to human-readable labels. */
export function humanLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Bytes ─────────────────────────────────────────────────────────────

export function formatBytes(value: unknown): string {
  if (value == null) return "No data";
  const num = Number(value);
  if (!Number.isFinite(num)) return "No data";
  if (num === 0) return "0 bytes";
  const units = ["bytes", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(num) / Math.log(1024)), units.length - 1);
  return `${(num / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
