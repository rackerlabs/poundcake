import { apiGet, apiPost } from "../lib/api-client.js";
import { $, $all, clearNode, el } from "../lib/dom.js";
import { formatDate, mapStatusClass } from "../lib/format.js";

let ctx = null;

function matcherRow(defaults = {}) {
  const row = el("div", { className: "kv-pair" });

  const keyInput = el("input", {
    attrs: {
      type: "text",
      placeholder: "label key (e.g. alertname)",
      value: defaults.label_key || "",
      class: "supp-match-key",
    },
  });

  const operator = el("select", { attrs: { class: "supp-match-operator" } });
  ["eq", "neq", "regex", "nregex", "exists", "not_exists"].forEach((item) => {
    const option = el("option", { attrs: { value: item }, text: item });
    operator.appendChild(option);
  });
  operator.value = defaults.operator || "eq";

  const valueInput = el("input", {
    attrs: {
      type: "text",
      placeholder: "value (optional for exists/not_exists)",
      value: defaults.value || "",
      class: "supp-match-value",
    },
  });

  const remove = el("button", {
    className: "btn small danger",
    text: "Remove",
    on: {
      click: () => {
        row.remove();
      },
    },
  });

  row.appendChild(keyInput);
  row.appendChild(operator);
  row.appendChild(valueInput);
  row.appendChild(remove);

  return row;
}

function readMatchers() {
  return $all("#supp-matcher-list .kv-pair")
    .map((row) => {
      const labelKey = row.querySelector(".supp-match-key")?.value?.trim();
      const operator = row.querySelector(".supp-match-operator")?.value;
      const value = row.querySelector(".supp-match-value")?.value?.trim();
      return {
        label_key: labelKey,
        operator,
        value: value || null,
      };
    })
    .filter((item) => item.label_key);
}

function renderSuppressedActivity(items) {
  const container = $("#suppressed-activity");
  clearNode(container);

  if (!Array.isArray(items) || !items.length) {
    container.appendChild(el("p", { className: "empty", text: "No suppressed activity." }));
    return;
  }

  items.forEach((item) => {
    const block = el("div", { className: "activity-item" }, [
      el("div", { className: "row between" }, [
        el("strong", { text: item.alertname || "Unknown" }),
        el("span", { className: `badge ${mapStatusClass(item.status)}`, text: item.status || "-" }),
      ]),
      el("div", { className: "muted", text: `Suppression #${item.suppression_id} | ${item.severity || "unknown"}` }),
      el("div", { className: "time", text: formatDate(item.received_at) }),
    ]);
    container.appendChild(block);
  });
}

export async function loadSuppressedActivity() {
  const data = await apiGet("/api/v1/activity/suppressed?limit=30");
  renderSuppressedActivity(data);
}

async function cancelSuppression(id) {
  const ok = await ctx.confirm(`Cancel suppression #${id}?`);
  if (!ok) return;

  await apiPost(`/api/v1/suppressions/${id}/cancel`, null);
  ctx.notify("success", `Suppression #${id} canceled`);
  await load();
  await ctx.refreshDashboard();
}

function suppressionTableRow(item, totalSuppressed = 0) {
  const tr = el("tr");
  tr.appendChild(el("td", { text: item.id }));

  const nameCell = el("td");
  nameCell.appendChild(el("strong", { text: item.name || "-" }));
  if (item.reason) {
    nameCell.appendChild(el("div", { className: "muted", text: item.reason }));
  }
  tr.appendChild(nameCell);

  tr.appendChild(el("td", {}, [
    el("span", { className: `badge ${mapStatusClass(item.status)}`, text: item.status || "unknown" }),
  ]));
  tr.appendChild(el("td", { text: item.scope || "-" }));
  tr.appendChild(el("td", { text: `${formatDate(item.starts_at)} / ${formatDate(item.ends_at)}` }));
  tr.appendChild(el("td", { text: totalSuppressed }));

  const actions = el("td");
  actions.appendChild(
    el("button", {
      className: "btn small danger",
      text: "Cancel",
      on: {
        click: () => cancelSuppression(item.id),
      },
    }),
  );
  tr.appendChild(actions);

  return tr;
}

export async function load() {
  const status = $("#suppression-status-filter")?.value || "";
  const url = status
    ? `/api/v1/suppressions?status=${encodeURIComponent(status)}`
    : "/api/v1/suppressions";

  const rows = await apiGet(url);
  const tbody = $("#supp-table-body");
  clearNode(tbody);

  if (!Array.isArray(rows) || !rows.length) {
    const tr = el("tr");
    tr.appendChild(el("td", { attrs: { colspan: "7" }, className: "empty", text: "No suppressions found" }));
    tbody.appendChild(tr);
  } else {
    for (const item of rows) {
      let totalSuppressed = 0;
      try {
        const stats = await apiGet(`/api/v1/suppressions/${item.id}/stats`);
        totalSuppressed = stats?.total_suppressed || 0;
      } catch {
        totalSuppressed = 0;
      }
      tbody.appendChild(suppressionTableRow(item, totalSuppressed));
    }
  }

  await loadSuppressedActivity();
}

export async function createSuppression() {
  const name = $("#supp-name")?.value?.trim();
  const reason = $("#supp-reason")?.value?.trim();
  const startsAt = $("#supp-starts-at")?.value?.trim();
  const endsAt = $("#supp-ends-at")?.value?.trim();
  const scope = $("#supp-scope")?.value || "matchers";
  const summaryTicketEnabled = Boolean($("#supp-summary-ticket")?.checked);

  if (!name || !startsAt || !endsAt) {
    ctx.notify("error", "Name, starts_at, and ends_at are required.");
    return;
  }

  const payload = {
    name,
    reason: reason || null,
    starts_at: startsAt,
    ends_at: endsAt,
    scope,
    created_by: "ui",
    summary_ticket_enabled: summaryTicketEnabled,
    enabled: true,
    matchers: [],
  };

  if (scope === "matchers") {
    const matchers = readMatchers();
    if (!matchers.length) {
      ctx.notify("error", "At least one matcher is required when scope=matchers.");
      return;
    }
    payload.matchers = matchers;
  }

  await apiPost("/api/v1/suppressions", payload);
  ctx.notify("success", "Suppression created");
  await load();
  await ctx.refreshDashboard();
}

export function init(context) {
  ctx = context;

  $("#supp-add-matcher")?.addEventListener("click", () => {
    $("#supp-matcher-list")?.appendChild(matcherRow());
  });

  $("#supp-create")?.addEventListener("click", () => {
    createSuppression().catch((error) => {
      ctx.notify("error", error.message);
    });
  });

  $("#suppression-refresh")?.addEventListener("click", () => {
    load().catch((error) => {
      ctx.notify("error", error.message);
    });
  });

  $("#suppression-status-filter")?.addEventListener("change", () => {
    load().catch((error) => {
      ctx.notify("error", error.message);
    });
  });

  if (!$all("#supp-matcher-list .kv-pair").length) {
    $("#supp-matcher-list")?.appendChild(matcherRow());
  }
}
