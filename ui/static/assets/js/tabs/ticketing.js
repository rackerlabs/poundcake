import { apiGet } from "../lib/api-client.js";
import { $, clearNode, el } from "../lib/dom.js";
import { formatDate, mapStatusClass, compactJson } from "../lib/format.js";

let ctx = null;
let rowsCache = [];

function renderDetails(index) {
  const details = $("#ticketing-details");
  clearNode(details);
  const item = rowsCache[index];
  if (!item) {
    details.appendChild(el("p", { className: "empty", text: "No details found." }));
    return;
  }

  details.appendChild(el("pre", { text: compactJson(item.details || {}) }));
}

function rowNode(item, index) {
  const tr = el("tr");
  const route = [item.execution_target, item.destination_target].filter(Boolean).join(" / ");
  tr.appendChild(el("td", { text: item.source || "-" }));
  tr.appendChild(el("td", { text: item.reference_id || "-" }));
  tr.appendChild(el("td", { text: route || "-" }));
  tr.appendChild(el("td", { text: item.ticket_id || "-" }));
  tr.appendChild(el("td", { text: item.operation_id || "-" }));
  tr.appendChild(el("td", {}, [
    el("span", { className: `badge ${mapStatusClass(item.status)}`, text: item.status || "-" }),
  ]));
  tr.appendChild(el("td", { text: formatDate(item.updated_at) }));

  const ops = el("td");
  ops.appendChild(
    el("button", {
      className: "btn small ghost",
      text: "View",
      on: {
        click: () => renderDetails(index),
      },
    }),
  );
  tr.appendChild(ops);

  return tr;
}

export async function load() {
  const status = $("#ticketing-status-filter")?.value?.trim() || "";
  const source = $("#ticketing-source-filter")?.value?.trim() || "";

  const endpoint = status
    ? `/api/v1/ticketing/bakery?status=${encodeURIComponent(status)}`
    : "/api/v1/ticketing/bakery";

  let data = await apiGet(endpoint);
  data = Array.isArray(data) ? data : [];

  if (source) {
    data = data.filter((item) => item.source === source);
  }

  rowsCache = data;
  const body = $("#ticketing-table-body");
  clearNode(body);

  if (!data.length) {
    const tr = el("tr");
    tr.appendChild(el("td", { attrs: { colspan: "8" }, className: "empty", text: "No Bakery records found" }));
    body.appendChild(tr);
    renderDetails(-1);
    return;
  }

  data.forEach((item, index) => {
    body.appendChild(rowNode(item, index));
  });

  renderDetails(0);
}

export function init(context) {
  ctx = context;

  $("#ticketing-refresh")?.addEventListener("click", () => {
    load().catch((error) => ctx.notify("error", error.message));
  });

  $("#ticketing-status-filter")?.addEventListener("change", () => {
    load().catch((error) => ctx.notify("error", error.message));
  });

  $("#ticketing-source-filter")?.addEventListener("change", () => {
    load().catch((error) => ctx.notify("error", error.message));
  });
}
