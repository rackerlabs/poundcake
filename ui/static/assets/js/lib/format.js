export function formatDate(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
}

export function titleCase(value) {
  if (!value) {
    return "-";
  }
  return String(value)
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

export function compactJson(value) {
  if (value == null) {
    return "-";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function mapStatusClass(status) {
  const key = String(status || "").toLowerCase();
  if (["complete", "succeeded", "success", "healthy", "active", "resolved"].includes(key)) {
    return "complete";
  }
  if (["failed", "error", "unhealthy", "canceled"].includes(key)) {
    return "failed";
  }
  if (["processing", "pending", "warning", "running"].includes(key)) {
    return "processing";
  }
  return "new";
}

export function truncate(value, max = 80) {
  const text = String(value || "");
  if (text.length <= max) {
    return text;
  }
  return `${text.slice(0, max - 1)}…`;
}
