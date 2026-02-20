import { apiGet } from "../lib/api-client.js";
import { $, clearNode, el, appendLabeledValue, copyText } from "../lib/dom.js";
import { formatDate, mapStatusClass, titleCase, compactJson } from "../lib/format.js";

let ctx = null;
let statsCache = null;

function renderStats(stats) {
  const container = $("#alerts-stats");
  clearNode(container);

  const statuses = ["new", "processing", "complete", "failed"];
  statuses.forEach((status) => {
    const count = stats?.alerts_by_processing_status?.[status] || 0;
    const item = el("div", { className: "card" }, [
      el("div", { className: "metric-label", text: titleCase(status) }),
      el("div", { className: "metric-value", text: count }),
    ]);
    item.style.padding = "12px";
    container.appendChild(item);
  });
}

function buildDetailsContent(order) {
  const wrap = el("div", { className: "stack" });
  appendLabeledValue(wrap, "Fingerprint", order.fingerprint || "-");
  appendLabeledValue(wrap, "Alert Status", order.alert_status || "-");
  appendLabeledValue(wrap, "Processing", order.processing_status || "-");
  appendLabeledValue(wrap, "Counter", order.counter ?? 0);
  appendLabeledValue(wrap, "Active", String(order.is_active));
  appendLabeledValue(wrap, "Started", formatDate(order.starts_at));
  appendLabeledValue(wrap, "Created", formatDate(order.created_at));
  appendLabeledValue(wrap, "Updated", formatDate(order.updated_at));

  const labelBlock = el("details", {}, [
    el("summary", { text: "Labels" }),
    el("pre", { text: compactJson(order.labels || {}) }),
  ]);
  wrap.appendChild(labelBlock);

  const actionRow = el("div", { className: "inline-actions" }, [
    el("button", {
      className: "btn small ghost",
      text: "Copy Fingerprint",
      on: {
        click: () => copyText(order.fingerprint),
      },
    }),
  ]);
  wrap.appendChild(actionRow);

  return wrap;
}

async function toggleDetails(orderId, detailsRow, detailsCell) {
  const isOpen = detailsRow.dataset.open === "true";
  if (isOpen) {
    detailsRow.style.display = "none";
    detailsRow.dataset.open = "false";
    return;
  }

  detailsRow.style.display = "table-row";
  detailsRow.dataset.open = "true";

  if (detailsRow.dataset.loaded === "true") {
    return;
  }

  clearNode(detailsCell);
  detailsCell.appendChild(el("p", { className: "muted", text: "Loading details..." }));

  try {
    const order = await apiGet(`/api/v1/orders/${orderId}`);
    clearNode(detailsCell);
    detailsCell.appendChild(buildDetailsContent(order));
    detailsRow.dataset.loaded = "true";
  } catch (error) {
    clearNode(detailsCell);
    detailsCell.appendChild(el("p", { className: "empty", text: error.message }));
  }
}

function buildOrderRow(order) {
  const tr = el("tr", { className: "expand-row" });
  const detailsRow = el("tr");
  detailsRow.style.display = "none";
  detailsRow.dataset.open = "false";

  const detailsCell = el("td", { attrs: { colspan: "8" } }, [
    el("div", { className: "details-panel" }),
  ]);
  detailsRow.appendChild(detailsCell);

  tr.addEventListener("click", () => {
    toggleDetails(order.id, detailsRow, detailsCell);
  });

  const instance = order.labels?.instance || order.labels?.pod || order.labels?.node || "-";
  const severity = order.labels?.severity || order.severity || "-";

  tr.appendChild(el("td", {}, [el("strong", { text: order.alert_group_name || "-" })]));
  tr.appendChild(el("td", { text: instance }));
  tr.appendChild(el("td", { text: severity }));
  tr.appendChild(el("td", {}, [el("span", { className: `badge ${mapStatusClass(order.processing_status)}`, text: order.processing_status || "unknown" })]));
  tr.appendChild(el("td", { text: order.alert_status || "-" }));
  tr.appendChild(el("td", { text: formatDate(order.created_at) }));
  tr.appendChild(el("td", { text: order.counter ?? 0 }));

  const actionsCell = el("td");
  const actions = el("div", { className: "inline-actions" });

  actions.appendChild(
    el("button", {
      className: "btn small primary",
      text: "Timeline",
      on: {
        click: async (event) => {
          event.stopPropagation();
          await loadTimeline(order.id);
        },
      },
    }),
  );

  actions.appendChild(
    el("button", {
      className: "btn small success",
      text: "Detail",
      on: {
        click: (event) => {
          event.stopPropagation();
          ctx.openIncident(order.id);
        },
      },
    }),
  );

  actionsCell.appendChild(actions);
  tr.appendChild(actionsCell);

  return { row: tr, detailsRow };
}

function renderTimelineEvents(events) {
  const container = $("#alerts-timeline");
  clearNode(container);

  if (!events.length) {
    container.appendChild(el("p", { className: "empty", text: "No timeline events available." }));
    return;
  }

  events.forEach((eventItem) => {
    const card = el("div", { className: "activity-item" });
    const top = el("div", { className: "row between" }, [
      el("strong", { text: eventItem.title || "Event" }),
      el("span", { className: `badge ${mapStatusClass(eventItem.status)}`, text: eventItem.status || "unknown" }),
    ]);
    card.appendChild(top);
    card.appendChild(el("div", { className: "time", text: `${formatDate(eventItem.timestamp)} | ${eventItem.event_type || "-"}` }));

    const correlationEntries = Object.entries(eventItem.correlation_ids || {}).filter(([, value]) => value);
    if (correlationEntries.length) {
      const idBox = el("div", { className: "stack" });
      correlationEntries.forEach(([key, value]) => {
        const row = el("div", { className: "inline-actions" }, [
          el("span", { text: `${key}: ${value}` }),
          el("button", {
            className: "btn small ghost",
            text: "Copy",
            on: {
              click: () => copyText(value),
            },
          }),
        ]);
        idBox.appendChild(row);
      });
      card.appendChild(idBox);
    }

    if (eventItem.details && Object.keys(eventItem.details).length) {
      card.appendChild(el("pre", { text: compactJson(eventItem.details) }));
    }

    container.appendChild(card);
  });
}

export async function loadTimeline(orderId) {
  const container = $("#alerts-timeline");
  clearNode(container);
  container.appendChild(el("p", { className: "muted", text: "Loading timeline..." }));

  try {
    const payload = await apiGet(`/api/v1/orders/${orderId}/timeline`);
    const events = Array.isArray(payload?.events) ? payload.events : [];
    renderTimelineEvents(events);
  } catch (error) {
    clearNode(container);
    container.appendChild(el("p", { className: "empty", text: error.message }));
  }
}

export async function load() {
  const filterStatus = $("#alerts-status-filter").value;
  const url = filterStatus ? `/api/v1/orders?processing_status=${encodeURIComponent(filterStatus)}` : "/api/v1/orders";

  try {
    const [ordersRaw, stats] = await Promise.all([
      apiGet(url),
      apiGet("/api/v1/stats"),
    ]);

    statsCache = stats;
    renderStats(stats);

    const orders = Array.isArray(ordersRaw) ? ordersRaw : ordersRaw?.orders || [];
    const body = $("#alerts-table-body");
    clearNode(body);

    if (!orders.length) {
      const tr = el("tr");
      tr.appendChild(el("td", { attrs: { colspan: "8" }, text: "No orders found", className: "empty" }));
      body.appendChild(tr);
      return;
    }

    orders.forEach((order) => {
      const { row, detailsRow } = buildOrderRow(order);
      body.appendChild(row);
      body.appendChild(detailsRow);
    });
  } catch (error) {
    ctx.notify("error", `Failed to load alerts: ${error.message}`);
  }
}

export function isAutoRefreshEnabled() {
  const checkbox = $("#alerts-auto-refresh");
  return Boolean(checkbox?.checked);
}

export function init(context) {
  ctx = context;

  $("#alerts-refresh")?.addEventListener("click", () => load());
  $("#alerts-status-filter")?.addEventListener("change", () => load());

  if (!$("#alerts-timeline")?.childNodes.length) {
    $("#alerts-timeline")?.appendChild(
      el("p", { className: "muted", text: "Select a timeline action to inspect incident events." }),
    );
  }
}
