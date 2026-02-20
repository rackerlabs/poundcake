import { apiGet } from "../lib/api-client.js";
import { $, clearNode, el, appendLabeledValue, copyText } from "../lib/dom.js";
import { compactJson, formatDate, mapStatusClass } from "../lib/format.js";
import { setCurrentIncidentOrderId } from "../lib/state.js";

let ctx = null;

function eventCard(eventItem) {
  const card = el("div", { className: "activity-item" });

  card.appendChild(
    el("div", { className: "row between" }, [
      el("strong", { text: eventItem.title || "Event" }),
      el("span", { className: `badge ${mapStatusClass(eventItem.status)}`, text: eventItem.status || "unknown" }),
    ]),
  );

  card.appendChild(
    el("div", {
      className: "time",
      text: `${formatDate(eventItem.timestamp)} | ${eventItem.event_type || "-"}`,
    }),
  );

  const ids = Object.entries(eventItem.correlation_ids || {}).filter(([, value]) => value);
  if (ids.length) {
    const idsWrap = el("div", { className: "stack" });
    ids.forEach(([key, value]) => {
      idsWrap.appendChild(
        el("div", { className: "inline-actions" }, [
          el("span", { text: `${key}: ${value}` }),
          el("button", {
            className: "btn small ghost",
            text: "Copy",
            on: {
              click: () => copyText(value),
            },
          }),
        ]),
      );
    });
    card.appendChild(idsWrap);
  }

  if (eventItem.details && Object.keys(eventItem.details).length) {
    card.appendChild(el("pre", { text: compactJson(eventItem.details) }));
  }

  return card;
}

function renderEventList(containerSelector, events, emptyMessage) {
  const container = $(containerSelector);
  clearNode(container);

  if (!events?.length) {
    container.appendChild(el("p", { className: "empty", text: emptyMessage }));
    return;
  }

  events.forEach((eventItem) => {
    container.appendChild(eventCard(eventItem));
  });
}

function renderOrderSummary(order) {
  const container = $("#incident-order-summary");
  clearNode(container);

  appendLabeledValue(container, "Order ID", order.id || "-");
  appendLabeledValue(container, "Group", order.alert_group_name || "-");
  appendLabeledValue(container, "Processing", order.processing_status || "-");
  appendLabeledValue(container, "Alert Status", order.alert_status || "-");
  appendLabeledValue(container, "Started", formatDate(order.starts_at));
  appendLabeledValue(container, "Created", formatDate(order.created_at));

  const reqRow = el("div", { className: "inline-actions" }, [
    el("span", { text: `Req ID: ${order.req_id || "-"}` }),
    el("button", {
      className: "btn small ghost",
      text: "Copy",
      on: { click: () => copyText(order.req_id) },
    }),
  ]);
  container.appendChild(reqRow);

  const fpRow = el("div", { className: "inline-actions" }, [
    el("span", { text: `Fingerprint: ${order.fingerprint || "-"}` }),
    el("button", {
      className: "btn small ghost",
      text: "Copy",
      on: { click: () => copyText(order.fingerprint) },
    }),
  ]);
  container.appendChild(fpRow);
}

function renderBakerySummary(events) {
  const container = $("#incident-bakery-summary");
  clearNode(container);

  if (!events.length) {
    container.appendChild(el("p", { className: "empty", text: "No Bakery operations linked." }));
    return;
  }

  events.forEach((eventItem) => {
    const card = eventCard(eventItem);
    const ticket = eventItem.correlation_ids?.bakery_ticket_id;
    const operation = eventItem.correlation_ids?.bakery_operation_id;

    const extra = el("div", { className: "inline-actions" });
    extra.appendChild(el("span", { text: `Ticket: ${ticket || "-"}` }));
    if (ticket) {
      extra.appendChild(el("button", {
        className: "btn small ghost",
        text: "Copy",
        on: { click: () => copyText(ticket) },
      }));
    }

    const extra2 = el("div", { className: "inline-actions" });
    extra2.appendChild(el("span", { text: `Operation: ${operation || "-"}` }));
    if (operation) {
      extra2.appendChild(el("button", {
        className: "btn small ghost",
        text: "Copy",
        on: { click: () => copyText(operation) },
      }));
    }

    card.appendChild(extra);
    card.appendChild(extra2);
    container.appendChild(card);
  });
}

export async function load(orderId = null) {
  const resolvedOrderId = Number(orderId || $("#incident-order-id")?.value || 0);
  if (!resolvedOrderId || Number.isNaN(resolvedOrderId)) {
    ctx.notify("error", "Order ID is required");
    return;
  }

  setCurrentIncidentOrderId(resolvedOrderId);
  ctx.setIncidentOrderId(resolvedOrderId);
  $("#incident-order-id").value = String(resolvedOrderId);

  const loadMark = $("#incident-last-load");
  if (loadMark) {
    loadMark.textContent = "Loading...";
  }

  try {
    const payload = await apiGet(`/api/v1/orders/${resolvedOrderId}/timeline`);
    const order = payload?.order || {};
    const events = Array.isArray(payload?.events) ? payload.events : [];

    renderOrderSummary(order);
    renderBakerySummary(events.filter((item) => item.event_type === "bakery"));
    renderEventList("#incident-dishes", events.filter((item) => item.event_type === "dish"), "No dish events.");
    renderEventList("#incident-tasks", events.filter((item) => item.event_type === "task"), "No task events.");
    renderEventList("#incident-full-timeline", events, "No timeline events.");

    if (loadMark) {
      loadMark.textContent = `Last refresh: ${new Date().toLocaleString()}`;
    }
  } catch (error) {
    ctx.notify("error", `Failed to load incident: ${error.message}`);
    renderEventList("#incident-dishes", [], "Failed to load dishes.");
    renderEventList("#incident-tasks", [], "Failed to load tasks.");
    renderEventList("#incident-full-timeline", [], "Failed to load timeline.");
  }
}

export async function open(orderId) {
  await ctx.switchTab("incident");
  await load(orderId);
}

export function init(context) {
  ctx = context;

  $("#incident-load-btn")?.addEventListener("click", () => {
    load();
  });

  $("#incident-order-id")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      load();
    }
  });
}
