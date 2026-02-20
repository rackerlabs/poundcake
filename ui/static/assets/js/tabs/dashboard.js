import { apiGet } from "../lib/api-client.js";
import { $, clearNode, el, appendLabeledValue } from "../lib/dom.js";
import { formatDate, mapStatusClass, truncate } from "../lib/format.js";

let ctx = null;

function healthCardClass(status) {
  if (status === "healthy") return "health-good";
  if (status === "degraded") return "health-warn";
  return "health-bad";
}

function renderHealthCards(health) {
  const container = $("#dashboard-metrics");
  clearNode(container);

  const overall = el("div", { className: `card ${healthCardClass(health.status)}` }, [
    el("h3", { text: "Overall System" }),
  ]);
  appendLabeledValue(overall, "Status", String(health.status || "unknown").toUpperCase());
  appendLabeledValue(overall, "Version", health.version || "-");
  appendLabeledValue(overall, "Instance", health.instance_id || "-");
  appendLabeledValue(overall, "Timestamp", formatDate(health.timestamp));
  container.appendChild(overall);

  const components = health.components || {};
  ["database", "stackstorm", "mongodb", "rabbitmq", "redis"].forEach((key) => {
    const component = components[key] || {};
    const card = el("div", { className: `card ${healthCardClass(component.status)}` }, [
      el("h3", { text: key.toUpperCase() }),
    ]);
    appendLabeledValue(card, "Status", String(component.status || "unknown").toUpperCase());
    appendLabeledValue(card, "Message", component.message || "-");
    container.appendChild(card);
  });
}

function renderQuickStats(stats, overview, rules, executions) {
  const quick = $("#dashboard-quick-stats");
  clearNode(quick);

  appendLabeledValue(quick, "Total Alerts", stats.total_alerts || 0);
  appendLabeledValue(quick, "Total Recipes", stats.total_recipes || 0);
  appendLabeledValue(quick, "Total Executions", stats.total_executions || 0);
  appendLabeledValue(quick, "Rules Firing", rules.filter((rule) => rule.state === "firing").length);
  appendLabeledValue(
    quick,
    "Failed Executions",
    (executions || []).filter((item) => ["failed", "error"].includes(String(item.status || "").toLowerCase())).length,
  );
  appendLabeledValue(quick, "Active Suppressions", overview?.suppressions?.active || 0);
}

function renderActivity(suppressedActivity = [], recentOrders = []) {
  const activity = $("#dashboard-activity");
  clearNode(activity);

  const entries = [];
  suppressedActivity.forEach((item) => {
    entries.push({
      title: `${item.alertname || "Unknown"} (${item.severity || "unknown"})`,
      subtitle: `Suppressed by window #${item.suppression_id}`,
      time: formatDate(item.received_at),
      status: "suppressed",
    });
  });

  recentOrders.slice(0, 10).forEach((item) => {
    entries.push({
      title: item.alert_group_name || `Order ${item.id}`,
      subtitle: `Processing: ${item.processing_status || "unknown"}`,
      time: formatDate(item.updated_at || item.created_at),
      status: item.processing_status || "new",
    });
  });

  entries
    .sort((a, b) => (new Date(b.time).getTime() || 0) - (new Date(a.time).getTime() || 0))
    .slice(0, 20)
    .forEach((entry) => {
      const status = mapStatusClass(entry.status);
      const item = el("div", { className: "activity-item" }, [
        el("div", { className: "row between" }, [
          el("strong", { text: truncate(entry.title, 90) }),
          el("span", { className: `badge ${status}`, text: status }),
        ]),
        el("div", { className: "muted", text: truncate(entry.subtitle, 120) }),
        el("div", { className: "time", text: entry.time }),
      ]);
      activity.appendChild(item);
    });

  if (!activity.childNodes.length) {
    activity.appendChild(el("p", { className: "empty", text: "No recent activity." }));
  }
}

function renderPlatformSummary(overview, stats) {
  const summary = $("#dashboard-platform-summary");
  clearNode(summary);

  appendLabeledValue(
    summary,
    "Order Queue (new/processing)",
    `${overview?.queue?.orders_new || 0}/${overview?.queue?.orders_processing || 0}`,
  );
  appendLabeledValue(summary, "Orders Failed", overview?.failures?.orders_failed || 0);
  appendLabeledValue(summary, "Dishes Failed", overview?.failures?.dishes_failed || 0);
  appendLabeledValue(summary, "Bakery Summary Failures", overview?.bakery?.summary_failures || 0);
  appendLabeledValue(summary, "Alerts (24h)", stats.recent_alerts || 0);

  const hints = overview?.failures?.runbook_hints || [];
  if (hints.length) {
    const hintTitle = el("h4", { text: "Runbook Hints" });
    hintTitle.style.marginTop = "12px";
    hintTitle.style.marginBottom = "8px";
    summary.appendChild(hintTitle);
    hints.forEach((hint) => {
      summary.appendChild(el("div", { className: "activity-item" }, [
        el("div", { text: hint }),
      ]));
    });
  }

  const topError = overview?.failures?.top_errors?.[0]?.error;
  if (topError) {
    const p = el("p", { className: "muted", text: `Top error: ${truncate(topError, 120)}` });
    p.style.marginTop = "10px";
    summary.appendChild(p);
  }
}

export function init(context) {
  ctx = context;
}

export async function load() {
  if (!ctx) return;
  try {
    const [health, stats, orders, rulesPayload, overview, suppressedActivity, executions] = await Promise.all([
      apiGet("/api/v1/health"),
      apiGet("/api/v1/stats"),
      apiGet("/api/v1/orders?limit=20"),
      apiGet("/api/v1/prometheus/rules"),
      apiGet("/api/v1/observability/overview"),
      apiGet("/api/v1/activity/suppressed?limit=10"),
      apiGet("/api/v1/cook/executions?limit=20"),
    ]);

    const ordersArray = Array.isArray(orders) ? orders : orders?.orders || [];
    const rules = rulesPayload?.rules || [];
    const executionsArray = Array.isArray(executions) ? executions : [];

    renderHealthCards(health);
    renderQuickStats(stats, overview, rules, executionsArray);
    renderActivity(suppressedActivity, ordersArray);
    renderPlatformSummary(overview, stats);

    const headerVersion = $("#header-version");
    if (headerVersion && health.version) {
      headerVersion.textContent = `v${health.version}`;
    }

    const headerStats = $("#header-stats");
    if (headerStats) {
      headerStats.textContent = `Alerts: ${stats.total_alerts || 0} | Recipes: ${stats.total_recipes || 0} | Executions: ${stats.total_executions || 0}`;
    }
  } catch (error) {
    ctx.notify("error", `Failed to load dashboard: ${error.message}`);
  }
}
