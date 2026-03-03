import { apiDelete, apiGet, apiPost, apiPut } from "../lib/api-client.js";
import { $, clearNode, el, appendLabeledValue } from "../lib/dom.js";
import { compactJson, formatDate } from "../lib/format.js";

let ctx = null;
let ingredientsCache = [];
let editingIngredientId = null;

function parseOptionalJson(raw, fieldName, options = {}) {
  const value = (raw || "").trim();
  if (!value) {
    return undefined;
  }
  const requireObject = options.requireObject === true;
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${fieldName} must be valid JSON`);
  }
  if (requireObject && (Array.isArray(parsed) || typeof parsed !== "object" || parsed === null)) {
    throw new Error(`${fieldName} must be a JSON object`);
  }
  return parsed;
}

function asInt(inputId, fallback = 0) {
  const raw = $(inputId)?.value ?? "";
  const parsed = Number.parseInt(String(raw), 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return parsed;
}

function resetForm() {
  editingIngredientId = null;
  $("#ingredient-form-title").textContent = "Create Ingredient";
  $("#ingredient-task-id").value = "";
  $("#ingredient-task-name").value = "";
  $("#ingredient-action-id").value = "";
  $("#ingredient-source-type").value = "undefined";
  $("#ingredient-purpose").value = "utility";
  $("#ingredient-blocking").value = "true";
  $("#ingredient-on-failure").value = "stop";
  $("#ingredient-expected-duration").value = "60";
  $("#ingredient-timeout-duration").value = "300";
  $("#ingredient-retry-count").value = "0";
  $("#ingredient-retry-delay").value = "5";
  $("#ingredient-action-payload").value = "";
  $("#ingredient-action-params").value = "";
}

function loadFormFromIngredient(ingredient) {
  editingIngredientId = ingredient.id;
  $("#ingredient-form-title").textContent = `Edit Ingredient #${ingredient.id}`;
  $("#ingredient-task-id").value = ingredient.execution_target || "";
  $("#ingredient-task-name").value = ingredient.task_key_template || "";
  $("#ingredient-action-id").value = ingredient.execution_id || ingredient.action_id || "";
  $("#ingredient-source-type").value = ingredient.execution_engine || "undefined";
  $("#ingredient-purpose").value =
    ingredient.execution_purpose || ingredient.ingredient_kind || "utility";
  $("#ingredient-blocking").value = String(Boolean(ingredient.is_blocking));
  $("#ingredient-on-failure").value = ingredient.on_failure || "stop";
  $("#ingredient-expected-duration").value = String(ingredient.expected_duration_sec || 60);
  $("#ingredient-timeout-duration").value = String(ingredient.timeout_duration_sec || 300);
  $("#ingredient-retry-count").value = String(ingredient.retry_count || 0);
  $("#ingredient-retry-delay").value = String(ingredient.retry_delay || 5);
  $("#ingredient-action-payload").value = ingredient.execution_payload
    ? JSON.stringify(ingredient.execution_payload, null, 2)
    : "";
  $("#ingredient-action-params").value = ingredient.execution_parameters
    ? JSON.stringify(ingredient.execution_parameters, null, 2)
    : "";
}

function payloadFromForm() {
  return {
    execution_target: ($("#ingredient-task-id")?.value || "").trim(),
    task_key_template: ($("#ingredient-task-name")?.value || "").trim(),
    execution_id: ($("#ingredient-action-id")?.value || "").trim() || null,
    execution_payload: parseOptionalJson(
      $("#ingredient-action-payload")?.value,
      "Execution Payload",
      { requireObject: true },
    ),
    execution_parameters: parseOptionalJson(
      $("#ingredient-action-params")?.value,
      "Action Parameters",
    ),
    execution_engine: ($("#ingredient-source-type")?.value || "undefined").trim() || "undefined",
    execution_purpose: ($("#ingredient-purpose")?.value || "utility").trim() || "utility",
    is_blocking: ($("#ingredient-blocking")?.value || "true") === "true",
    expected_duration_sec: asInt("#ingredient-expected-duration", 60),
    timeout_duration_sec: asInt("#ingredient-timeout-duration", 300),
    retry_count: asInt("#ingredient-retry-count", 0),
    retry_delay: asInt("#ingredient-retry-delay", 5),
    on_failure: ($("#ingredient-on-failure")?.value || "stop").trim() || "stop",
  };
}

function renderIngredientDetail(ingredient) {
  const detail = $("#ingredient-detail");
  clearNode(detail);

  if (!ingredient) {
    detail.className = "details-panel muted";
    detail.textContent = "Select an ingredient to view details.";
    return;
  }

  detail.className = "details-panel";
  appendLabeledValue(detail, "ID", ingredient.id);
  appendLabeledValue(detail, "Execution Target", ingredient.execution_target);
  appendLabeledValue(detail, "Task Key Template", ingredient.task_key_template);
  appendLabeledValue(
    detail,
    "Execution ID",
    ingredient.execution_id || ingredient.action_id || "-",
  );
  appendLabeledValue(detail, "Execution Engine", ingredient.execution_engine || "-");
  appendLabeledValue(
    detail,
    "Execution Purpose",
    ingredient.execution_purpose || ingredient.ingredient_kind || "-",
  );
  appendLabeledValue(detail, "Blocking", String(Boolean(ingredient.is_blocking)));
  appendLabeledValue(
    detail,
    "Expected/Timeout",
    `${ingredient.expected_duration_sec || "-"} / ${ingredient.timeout_duration_sec || "-"}`,
  );
  appendLabeledValue(detail, "Retry", `${ingredient.retry_count || 0} @ ${ingredient.retry_delay || 0}s`);
  appendLabeledValue(detail, "On Failure", ingredient.on_failure || "-");
  appendLabeledValue(detail, "Updated", formatDate(ingredient.updated_at));

  const executionPayload = el("pre", { text: compactJson(ingredient.execution_payload) });
  executionPayload.style.marginTop = "8px";
  detail.appendChild(el("h4", { text: "Execution Payload" }));
  detail.appendChild(executionPayload);

  const payload = el("pre", { text: compactJson(ingredient.execution_parameters) });
  payload.style.marginTop = "8px";
  detail.appendChild(el("h4", { text: "Action Parameters" }));
  detail.appendChild(payload);
}

function ingredientRow(ingredient) {
  const tr = el("tr");

  tr.appendChild(el("td", { text: ingredient.id }));
  tr.appendChild(el("td", { text: ingredient.execution_target }));
  tr.appendChild(el("td", { text: ingredient.task_key_template }));
  tr.appendChild(el("td", { text: ingredient.execution_id || ingredient.action_id || "-" }));
  tr.appendChild(el("td", { text: String(Boolean(ingredient.is_blocking)) }));
  tr.appendChild(
    el("td", {
      text: `${ingredient.expected_duration_sec || "-"} / ${ingredient.timeout_duration_sec || "-"}`,
    }),
  );
  tr.appendChild(el("td", { text: `${ingredient.retry_count || 0} @ ${ingredient.retry_delay || 0}s` }));
  tr.appendChild(el("td", { text: formatDate(ingredient.updated_at) }));

  const ops = el("td", { className: "inline-actions" });
  ops.appendChild(
    el("button", {
      className: "btn small primary",
      text: "Edit",
      on: {
        click: () => {
          loadFormFromIngredient(ingredient);
          renderIngredientDetail(ingredient);
        },
      },
    }),
  );
  ops.appendChild(
    el("button", {
      className: "btn small ghost",
      text: "View",
      on: {
        click: () => renderIngredientDetail(ingredient),
      },
    }),
  );
  ops.appendChild(
    el("button", {
      className: "btn small danger",
      text: "Delete",
      on: {
        click: async () => {
          const ok = await ctx.confirm(
            `Delete ingredient '${ingredient.execution_target}' (ID ${ingredient.id})?`,
          );
          if (!ok) {
            return;
          }
          await apiDelete(`/api/v1/ingredients/${ingredient.id}`);
          ctx.notify("success", `Ingredient ${ingredient.id} deleted.`);
          await load();
          if (editingIngredientId === ingredient.id) {
            resetForm();
          }
        },
      },
    }),
  );
  tr.appendChild(ops);

  return tr;
}

function renderTable() {
  const body = $("#ingredients-table-body");
  clearNode(body);

  if (!ingredientsCache.length) {
    const tr = el("tr");
    tr.appendChild(
      el("td", {
        attrs: { colspan: "9" },
        className: "empty",
        text: "No ingredients found.",
      }),
    );
    body.appendChild(tr);
    return;
  }

  ingredientsCache.forEach((ingredient) => {
    body.appendChild(ingredientRow(ingredient));
  });
}

async function saveIngredient(event) {
  event.preventDefault();
  const payload = payloadFromForm();

  if (!payload.execution_target || !payload.task_key_template) {
    throw new Error("Execution Target and Task Key Template are required.");
  }

  if (editingIngredientId) {
    await apiPut(`/api/v1/ingredients/${editingIngredientId}`, payload);
    ctx.notify("success", `Ingredient ${editingIngredientId} updated.`);
  } else {
    await apiPost("/api/v1/ingredients/", payload);
    ctx.notify("success", "Ingredient created.");
  }

  resetForm();
  await load();
}

export async function load() {
  const ingredients = await apiGet("/api/v1/ingredients/?limit=500");
  ingredientsCache = Array.isArray(ingredients) ? ingredients : [];
  renderTable();
}

export function init(context) {
  ctx = context;
  resetForm();
  renderIngredientDetail(null);

  $("#ingredients-refresh")?.addEventListener("click", () => {
    load().catch((error) => ctx.notify("error", error.message));
  });
  $("#ingredients-new")?.addEventListener("click", () => {
    resetForm();
    renderIngredientDetail(null);
  });
  $("#ingredient-cancel")?.addEventListener("click", () => {
    resetForm();
    renderIngredientDetail(null);
  });
  $("#ingredient-form")?.addEventListener("submit", (event) => {
    saveIngredient(event).catch((error) => ctx.notify("error", error.message));
  });
}
