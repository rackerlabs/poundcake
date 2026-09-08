export function formatDate(value?: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function formatLongDate(value?: string | null): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function titleize(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function compactJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

export function localDatetimeInputValue(value?: Date): string {
  const date = value || new Date();
  const pad = (item: number) => String(item).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function datetimeLocalToUtcIso(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toISOString();
}

export function isPermanentSuppressionEnd(value?: string | null): boolean {
  if (!value) {
    return false;
  }
  const date = new Date(value);
  return !Number.isNaN(date.getTime()) && date.getUTCFullYear() >= 2099;
}

export function formatSuppressionEndsAt(value?: string | null): string {
  if (isPermanentSuppressionEnd(value)) {
    return "Until canceled";
  }
  return formatDate(value);
}

export function statusTone(value?: string | null): string {
  const normalized = String(value || "unknown").toLowerCase();
  if (["healthy", "complete", "success", "succeeded", "delivered", "active", "sent"].includes(normalized)) {
    return "good";
  }
  if (["failed", "error", "canceled", "unhealthy"].includes(normalized)) {
    return "bad";
  }
  if (["processing", "pending", "new", "warning", "degraded", "running", "created", "reused", "initializing"].includes(normalized)) {
    return "warn";
  }
  return "neutral";
}
