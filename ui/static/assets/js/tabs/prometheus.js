import { apiDelete, apiGet, apiPost, apiPut } from "../lib/api-client.js";
import { $, clearNode, el } from "../lib/dom.js";
import { mapStatusClass, truncate } from "../lib/format.js";

let ctx = null;
let settingsCache = null;
let rulesCache = [];

function parseJsonObject(inputValue, fieldName) {
  const raw = (inputValue || "").trim();
  if (!raw) {
    return undefined;
  }

  let parsed = null;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`${fieldName} must be valid JSON object`);
  }

  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${fieldName} must be a JSON object`);
  }

  return parsed;
}

function setPersistenceStatus(settings) {
  const target = $("#prom-persistence-status");
  if (!target) return;

  const parts = [];
  if (settings.prometheus_use_crds) {
    parts.push(`CRD (${settings.prometheus_crd_namespace})`);
  }
  if (settings.git_enabled) {
    parts.push(`Git (${settings.git_provider})`);
  }

  if (!parts.length) {
    target.textContent = "No backend configured";
    target.className = "badge failed";
    return;
  }

  target.textContent = parts.join(" | ");
  target.className = "badge complete";
}

function normalizedDuration(value) {
  if (!value) return "-";
  if (typeof value === "string" && /[smhdwy]$/.test(value)) {
    return value;
  }
  return `${value}s`;
}

function ruleRow(rule, canEdit) {
  const source = rule.crd || rule.file || "-";
  const tr = el("tr");

  tr.appendChild(el("td", {}, [el("strong", { text: rule.name || "-" })]));
  tr.appendChild(el("td", { text: rule.group || "-" }));
  tr.appendChild(el("td", { text: normalizedDuration(rule.duration) }));
  tr.appendChild(el("td", { text: source }));
  tr.appendChild(el("td", {}, [
    el("span", { className: `badge ${mapStatusClass(rule.state || "unknown")}`, text: rule.state || "unknown" }),
  ]));
  tr.appendChild(el("td", {}, [
    el("code", { text: truncate(rule.query || "", 80) }),
  ]));

  const ops = el("td", { className: "inline-actions" });
  if (canEdit) {
    ops.appendChild(el("button", {
      className: "btn small primary",
      text: "Edit",
      on: {
        click: () => openModal("edit", rule),
      },
    }));
    ops.appendChild(el("button", {
      className: "btn small danger",
      text: "Delete",
      on: {
        click: () => deleteRule(rule),
      },
    }));
  } else {
    ops.appendChild(el("span", { className: "muted", text: "Read-only" }));
  }
  tr.appendChild(ops);

  return tr;
}

function getFilteredRules() {
  const state = $("#prom-state-filter")?.value || "";
  const search = ($("#prom-search")?.value || "").toLowerCase();

  return rulesCache.filter((rule) => {
    if (state && String(rule.state || "").toLowerCase() !== state.toLowerCase()) {
      return false;
    }

    if (!search) {
      return true;
    }

    const haystack = [
      rule.name,
      rule.group,
      rule.query,
      rule.file,
      rule.crd,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    return haystack.includes(search);
  });
}

function renderRules() {
  const body = $("#prom-table-body");
  clearNode(body);

  const rules = getFilteredRules();
  const canEdit = Boolean(settingsCache?.prometheus_use_crds || settingsCache?.git_enabled);

  if (!rules.length) {
    const tr = el("tr");
    tr.appendChild(el("td", {
      attrs: { colspan: "7" },
      className: "empty",
      text: "No rules found",
    }));
    body.appendChild(tr);
    return;
  }

  rules.forEach((rule) => {
    body.appendChild(ruleRow(rule, canEdit));
  });
}

function openModal(mode, rule = null) {
  const root = $("#prom-modal-root");
  const title = $("#prom-modal-title");
  const form = $("#prom-form");

  form.dataset.mode = mode;
  title.textContent = mode === "create" ? "Create Prometheus Rule" : "Edit Prometheus Rule";

  const name = $("#prom-name");
  const group = $("#prom-group");
  const file = $("#prom-file");
  const expr = $("#prom-expr");
  const duration = $("#prom-for");
  const labels = $("#prom-labels");
  const annotations = $("#prom-annotations");

  if (!rule) {
    name.value = "";
    group.value = "";
    file.value = "";
    expr.value = "";
    duration.value = "";
    labels.value = "";
    annotations.value = "";
    name.disabled = false;
  } else {
    name.value = rule.name || "";
    group.value = rule.group || "";
    file.value = rule.crd || rule.file || "";
    expr.value = rule.query || "";
    duration.value = rule.duration || "";
    labels.value = rule.labels && Object.keys(rule.labels).length ? JSON.stringify(rule.labels, null, 2) : "";
    annotations.value =
      rule.annotations && Object.keys(rule.annotations).length
        ? JSON.stringify(rule.annotations, null, 2)
        : "";
    name.disabled = mode === "edit";
  }

  root.classList.add("is-open");
}

function closeModal() {
  $("#prom-modal-root")?.classList.remove("is-open");
}

async function deleteRule(rule) {
  const source = rule.crd || rule.file || "";
  const ok = await ctx.confirm(
    `Delete rule "${rule.name}" from group "${rule.group}"? This uses the configured CRD/Git backend.`,
  );
  if (!ok) {
    return;
  }

  const result = await apiDelete(
    `/api/v1/prometheus/rules/${encodeURIComponent(rule.name)}?group_name=${encodeURIComponent(
      rule.group,
    )}&file_name=${encodeURIComponent(source)}`,
  );

  const message = [];
  message.push("Rule deleted.");
  if (result?.crd?.action) {
    message.push(`CRD: ${result.crd.action}`);
  }
  if (result?.git?.branch) {
    message.push(`Git branch: ${result.git.branch}`);
  }
  if (result?.git?.pull_request?.url) {
    message.push(`PR: ${result.git.pull_request.url}`);
  }
  if (result?.git_error) {
    message.push(`Git error: ${result.git_error}`);
  }

  ctx.notify("success", message.join(" | "));
  await load();
}

async function saveRule(event) {
  event.preventDefault();

  const mode = $("#prom-form")?.dataset.mode || "edit";
  const name = $("#prom-name")?.value?.trim();
  const group = $("#prom-group")?.value?.trim();
  const file = $("#prom-file")?.value?.trim();
  const expr = $("#prom-expr")?.value?.trim();
  const duration = $("#prom-for")?.value?.trim();

  if (!name || !group || !file || !expr) {
    throw new Error("Name, group, file/CRD, and expression are required.");
  }

  const labels = parseJsonObject($("#prom-labels")?.value, "Labels");
  const annotations = parseJsonObject($("#prom-annotations")?.value, "Annotations");

  const ruleData = {
    alert: name,
    expr,
    for: duration || undefined,
    labels,
    annotations,
  };

  let result = null;
  if (mode === "create") {
    result = await apiPost(
      `/api/v1/prometheus/rules?rule_name=${encodeURIComponent(name)}&group_name=${encodeURIComponent(
        group,
      )}&file_name=${encodeURIComponent(file)}`,
      ruleData,
    );
  } else {
    result = await apiPut(
      `/api/v1/prometheus/rules/${encodeURIComponent(name)}?group_name=${encodeURIComponent(
        group,
      )}&file_name=${encodeURIComponent(file)}`,
      ruleData,
    );
  }

  const message = [];
  message.push(mode === "create" ? "Rule created." : "Rule updated.");
  if (result?.crd?.action) {
    message.push(`CRD: ${result.crd.action}`);
  }
  if (result?.git?.branch) {
    message.push(`Git branch: ${result.git.branch}`);
  }
  if (result?.git?.pull_request?.url) {
    message.push(`PR: ${result.git.pull_request.url}`);
  }
  if (result?.git_error) {
    message.push(`Git error: ${result.git_error}`);
  }

  closeModal();
  ctx.notify("success", message.join(" | "));
  await load();
}

export async function load() {
  const [settings, rulesPayload] = await Promise.all([
    apiGet("/api/v1/settings"),
    apiGet("/api/v1/prometheus/rules"),
  ]);

  settingsCache = settings;
  rulesCache = Array.isArray(rulesPayload?.rules) ? rulesPayload.rules : [];

  setPersistenceStatus(settings);
  renderRules();
}

export function init(context) {
  ctx = context;

  $("#prom-refresh")?.addEventListener("click", () => {
    load().catch((error) => ctx.notify("error", error.message));
  });
  $("#prom-state-filter")?.addEventListener("change", () => renderRules());
  $("#prom-search")?.addEventListener("input", () => renderRules());
  $("#prom-create")?.addEventListener("click", () => openModal("create"));

  $("#prom-modal-cancel")?.addEventListener("click", () => closeModal());
  $("#prom-modal-root")?.addEventListener("click", (event) => {
    if (event.target.id === "prom-modal-root") {
      closeModal();
    }
  });
  $("#prom-form")?.addEventListener("submit", (event) => {
    saveRule(event).catch((error) => ctx.notify("error", error.message));
  });
}
