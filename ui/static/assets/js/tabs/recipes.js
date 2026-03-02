import { apiDelete, apiGet, apiPost, apiPut } from "../lib/api-client.js";
import { $, clearNode, el, appendLabeledValue } from "../lib/dom.js";
import { compactJson, formatDate } from "../lib/format.js";

let ctx = null;
let recipesCache = [];
let ingredientsCache = [];
let editingRecipeId = null;

function parseOptionalJson(raw, fieldName) {
  const value = (raw || "").trim();
  if (!value) {
    return undefined;
  }
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(`${fieldName} must be valid JSON`);
  }
}

function asInt(raw, fallback = 0) {
  const parsed = Number.parseInt(String(raw || ""), 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return parsed;
}

function ingredientOptions(selectedId = null) {
  const options = [el("option", { attrs: { value: "" }, text: "Select ingredient" })];
  ingredientsCache.forEach((ingredient) => {
    const option = el("option", {
      attrs: { value: ingredient.id },
      text: `${ingredient.id} - ${ingredient.execution_target}`,
    });
    if (selectedId && Number(selectedId) === Number(ingredient.id)) {
      option.selected = true;
    }
    options.push(option);
  });
  return options;
}

function recipeIngredientRow(item = null, disabled = false) {
  const wrapper = el("div", { className: "kv-pair" });

  const ingredientSelect = el("select", {}, ingredientOptions(item?.ingredient_id || null));
  ingredientSelect.disabled = disabled;

  const stepOrder = el("input", {
    attrs: { type: "number", min: "1", value: String(item?.step_order || 1) },
  });
  stepOrder.disabled = disabled;

  const onSuccess = el(
    "select",
    {},
    [
      el("option", { attrs: { value: "continue" }, text: "continue" }),
      el("option", { attrs: { value: "stop" }, text: "stop" }),
    ],
  );
  onSuccess.value = item?.on_success || "continue";
  onSuccess.disabled = disabled;

  const advanced = el("div", { className: "inline-actions" });
  const parallelInput = el("input", {
    attrs: {
      type: "number",
      min: "0",
      value: String(item?.parallel_group || 0),
      title: "parallel_group",
      placeholder: "Parallel",
    },
  });
  parallelInput.style.width = "92px";
  parallelInput.disabled = disabled;
  const depthInput = el("input", {
    attrs: {
      type: "number",
      min: "0",
      value: String(item?.depth || 0),
      title: "depth",
      placeholder: "Depth",
    },
  });
  depthInput.style.width = "92px";
  depthInput.disabled = disabled;
  const paramsInput = el("input", {
    attrs: {
      type: "text",
      value: item?.execution_parameters_override
        ? JSON.stringify(item.execution_parameters_override)
        : "",
      placeholder: "execution_parameters_override JSON",
    },
  });
  paramsInput.style.minWidth = "240px";
  paramsInput.disabled = disabled;
  advanced.appendChild(parallelInput);
  advanced.appendChild(depthInput);
  advanced.appendChild(paramsInput);

  const remove = el("button", {
    className: "btn small danger",
    text: "Remove",
    attrs: { type: "button" },
    on: {
      click: () => wrapper.remove(),
    },
  });
  remove.disabled = disabled;

  wrapper.appendChild(ingredientSelect);
  wrapper.appendChild(stepOrder);
  wrapper.appendChild(onSuccess);
  wrapper.appendChild(advanced);
  wrapper.appendChild(remove);

  wrapper.dataset.role = "recipe-ingredient-row";
  return wrapper;
}

function gatherRecipeIngredients() {
  const rows = Array.from(
    $("#recipe-ingredient-list")?.querySelectorAll('[data-role="recipe-ingredient-row"]') || [],
  );

  return rows.map((row) => {
    const [ingredientSelect, stepOrder, onSuccess, advanced] = row.children;
    const [parallelInput, depthInput, paramsInput] = advanced.querySelectorAll("input");
    return {
      ingredient_id: asInt(ingredientSelect.value, 0),
      step_order: asInt(stepOrder.value, 1),
      on_success: onSuccess.value || "continue",
      parallel_group: asInt(parallelInput.value, 0),
      depth: asInt(depthInput.value, 0),
      execution_parameters_override: parseOptionalJson(
        paramsInput.value,
        "Recipe ingredient execution_parameters_override",
      ),
    };
  });
}

function resetRecipeForm() {
  editingRecipeId = null;
  $("#recipe-form-title").textContent = "Create Recipe";
  $("#recipe-name").value = "";
  $("#recipe-name").disabled = false;
  $("#recipe-description").value = "";
  $("#recipe-enabled").value = "true";
  $("#recipe-source-type").value = "undefined";
  $("#recipe-workflow-id").value = "";
  $("#recipe-workflow-payload").value = "";
  $("#recipe-workflow-params").value = "";
  clearNode($("#recipe-ingredient-list"));
  $("#recipe-add-ingredient").disabled = false;
  $("#recipe-ingredient-list").appendChild(recipeIngredientRow());
}

function fillRecipeForm(recipe) {
  editingRecipeId = recipe.id;
  $("#recipe-form-title").textContent = `Edit Recipe #${recipe.id}`;
  $("#recipe-name").value = recipe.name || "";
  $("#recipe-name").disabled = true;
  $("#recipe-description").value = recipe.description || "";
  $("#recipe-enabled").value = String(Boolean(recipe.enabled));
  $("#recipe-source-type").value = "undefined";
  $("#recipe-workflow-id").value = "";
  $("#recipe-workflow-payload").value = "";
  $("#recipe-workflow-params").value = "";

  clearNode($("#recipe-ingredient-list"));
  const recipeIngredients = Array.isArray(recipe.recipe_ingredients)
    ? recipe.recipe_ingredients
    : [];
  if (!recipeIngredients.length) {
    $("#recipe-ingredient-list").appendChild(recipeIngredientRow(null, true));
  } else {
    recipeIngredients.forEach((item) => {
      $("#recipe-ingredient-list").appendChild(recipeIngredientRow(item, true));
    });
  }
  $("#recipe-add-ingredient").disabled = true;
}

function renderRecipeDetail(recipe) {
  const detail = $("#recipe-detail");
  clearNode(detail);

  if (!recipe) {
    detail.className = "details-panel muted";
    detail.textContent = "Select a recipe to view details.";
    return;
  }

  detail.className = "details-panel";
  appendLabeledValue(detail, "ID", recipe.id);
  appendLabeledValue(detail, "Name", recipe.name);
  appendLabeledValue(detail, "Enabled", String(Boolean(recipe.enabled)));
  appendLabeledValue(
    detail,
    "Ingredient Links",
    Array.isArray(recipe.recipe_ingredients) ? recipe.recipe_ingredients.length : 0,
  );
  appendLabeledValue(detail, "Updated", formatDate(recipe.updated_at));

  const links = el("div", { className: "mt-4" });
  links.appendChild(el("strong", { text: "Recipe Ingredients" }));
  const list = el("div", { className: "stack mt-4" });
  const recipeIngredients = Array.isArray(recipe.recipe_ingredients)
    ? recipe.recipe_ingredients
    : [];
  if (!recipeIngredients.length) {
    list.appendChild(el("div", { className: "muted", text: "None linked." }));
  } else {
    recipeIngredients
      .slice()
      .sort((a, b) => (a.step_order || 0) - (b.step_order || 0))
      .forEach((item) => {
        const ingredientName =
          item.ingredient?.execution_target || `ingredient:${item.ingredient_id}`;
        list.appendChild(
          el("div", { className: "activity-item" }, [
            el("div", { text: `#${item.step_order} ${ingredientName}` }),
            el("div", {
              className: "muted",
              text: `on_success=${item.on_success} parallel=${item.parallel_group} depth=${item.depth}`,
            }),
          ]),
        );
      });
  }
  links.appendChild(list);
  detail.appendChild(links);

  const payloads = el("div", { className: "mt-4" });
  payloads.appendChild(el("h4", { text: "Recipe Metadata" }));
  payloads.appendChild(el("pre", { text: compactJson({ name: recipe.name, enabled: recipe.enabled }) }));
  detail.appendChild(payloads);
}

function recipeRow(recipe) {
  const tr = el("tr");
  tr.appendChild(el("td", { text: recipe.id }));
  tr.appendChild(el("td", { text: recipe.name || "-" }));
  tr.appendChild(el("td", { text: String(Boolean(recipe.enabled)) }));
  tr.appendChild(el("td", { text: "-" }));
  tr.appendChild(
    el("td", {
      text: Array.isArray(recipe.recipe_ingredients) ? recipe.recipe_ingredients.length : 0,
    }),
  );
  tr.appendChild(el("td", { text: "-" }));
  tr.appendChild(el("td", { text: formatDate(recipe.updated_at) }));

  const ops = el("td", { className: "inline-actions" });
  ops.appendChild(
    el("button", {
      className: "btn small ghost",
      text: "View",
      on: {
        click: () => renderRecipeDetail(recipe),
      },
    }),
  );
  ops.appendChild(
    el("button", {
      className: "btn small primary",
      text: "Edit",
      on: {
        click: () => {
          fillRecipeForm(recipe);
          renderRecipeDetail(recipe);
          ctx.notify(
            "success",
            "Editing metadata only. Recipe ingredient links are editable on create.",
          );
        },
      },
    }),
  );
  ops.appendChild(
    el("button", {
      className: "btn small danger",
      text: "Delete",
      on: {
        click: async () => {
          const ok = await ctx.confirm(`Delete recipe '${recipe.name}' (ID ${recipe.id})?`);
          if (!ok) {
            return;
          }
          await apiDelete(`/api/v1/recipes/${recipe.id}`);
          ctx.notify("success", `Recipe ${recipe.id} deleted.`);
          await load();
          if (editingRecipeId === recipe.id) {
            resetRecipeForm();
          }
        },
      },
    }),
  );
  tr.appendChild(ops);

  return tr;
}

function renderTable() {
  const body = $("#recipes-table-body");
  clearNode(body);

  if (!recipesCache.length) {
    const tr = el("tr");
    tr.appendChild(
      el("td", {
        attrs: { colspan: "8" },
        className: "empty",
        text: "No recipes found.",
      }),
    );
    body.appendChild(tr);
    return;
  }

  recipesCache.forEach((recipe) => {
    body.appendChild(recipeRow(recipe));
  });
}

async function refreshLookups() {
  const ingredients = await apiGet("/api/v1/ingredients/?limit=500");
  ingredientsCache = Array.isArray(ingredients) ? ingredients : [];
}

async function saveRecipe(event) {
  event.preventDefault();

  const name = ($("#recipe-name")?.value || "").trim();
  const payload = {
    name,
    description: ($("#recipe-description")?.value || "").trim() || null,
    enabled: ($("#recipe-enabled")?.value || "true") === "true",
  };

  if (!editingRecipeId) {
    if (!name) {
      throw new Error("Recipe name is required.");
    }
    const recipeIngredients = gatherRecipeIngredients().filter((item) => item.ingredient_id > 0);
    if (!recipeIngredients.length) {
      throw new Error("At least one recipe ingredient is required.");
    }
    await apiPost("/api/v1/recipes/", {
      ...payload,
      recipe_ingredients: recipeIngredients,
    });
    ctx.notify("success", "Recipe created.");
  } else {
    await apiPut(`/api/v1/recipes/${editingRecipeId}`, payload);
    ctx.notify("success", `Recipe ${editingRecipeId} updated.`);
  }

  resetRecipeForm();
  await load();
}

export async function load() {
  await refreshLookups();
  const recipes = await apiGet("/api/v1/recipes/?limit=500");
  recipesCache = Array.isArray(recipes) ? recipes : [];
  renderTable();
}

export function init(context) {
  ctx = context;
  resetRecipeForm();
  renderRecipeDetail(null);

  $("#recipes-refresh")?.addEventListener("click", () => {
    load().catch((error) => ctx.notify("error", error.message));
  });
  $("#recipes-new")?.addEventListener("click", () => {
    resetRecipeForm();
    renderRecipeDetail(null);
  });
  $("#recipe-cancel")?.addEventListener("click", () => {
    resetRecipeForm();
    renderRecipeDetail(null);
  });
  $("#recipe-add-ingredient")?.addEventListener("click", () => {
    $("#recipe-ingredient-list").appendChild(recipeIngredientRow());
  });
  $("#recipe-form")?.addEventListener("submit", (event) => {
    saveRecipe(event).catch((error) => ctx.notify("error", error.message));
  });
}
