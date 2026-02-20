import { apiGet } from "../lib/api-client.js";
import { $, clearNode, el } from "../lib/dom.js";
import { formatDate, mapStatusClass } from "../lib/format.js";

let ctx = null;

function historyRow(item) {
  const tr = el("tr");

  const alertName =
    item.recipe?.name ||
    item.req_id ||
    (item.order_id ? `Order ${item.order_id}` : "Unknown");
  const actionName = item.recipe?.workflow_id || "Recipe dispatch";
  const started = item.started_at || item.created_at;

  tr.appendChild(el("td", { text: alertName }));
  tr.appendChild(el("td", { text: actionName }));
  tr.appendChild(
    el("td", {}, [
      el("span", {
        className: `badge ${mapStatusClass(item.processing_status)}`,
        text: item.processing_status || "unknown",
      }),
    ]),
  );
  tr.appendChild(el("td", { text: formatDate(started) }));
  tr.appendChild(el("td", { text: item.workflow_execution_id || "-" }));

  return tr;
}

export async function load() {
  const data = await apiGet("/api/v1/dishes?limit=50");
  const rows = Array.isArray(data) ? data : [];

  const body = $("#history-table-body");
  clearNode(body);

  if (!rows.length) {
    const tr = el("tr");
    tr.appendChild(el("td", { attrs: { colspan: "5" }, className: "empty", text: "No execution history found." }));
    body.appendChild(tr);
    return;
  }

  rows.forEach((row) => {
    body.appendChild(historyRow(row));
  });
}

export function init(context) {
  ctx = context;
  $("#history-refresh")?.addEventListener("click", () => {
    load().catch((error) => ctx.notify("error", error.message));
  });
}
