export function $(selector, root = document) {
  return root.querySelector(selector);
}

export function $all(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

export function clearNode(node) {
  while (node && node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

export function textNode(value) {
  return document.createTextNode(value == null ? "" : String(value));
}

export function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  const {
    className,
    text,
    attrs,
    dataset,
    on,
  } = options;

  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = String(text);
  }
  if (attrs) {
    Object.entries(attrs).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        node.setAttribute(key, String(value));
      }
    });
  }
  if (dataset) {
    Object.entries(dataset).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        node.dataset[key] = String(value);
      }
    });
  }
  if (on) {
    Object.entries(on).forEach(([event, handler]) => {
      node.addEventListener(event, handler);
    });
  }

  children.forEach((child) => {
    if (child == null) {
      return;
    }
    if (typeof child === "string" || typeof child === "number") {
      node.appendChild(textNode(child));
      return;
    }
    node.appendChild(child);
  });

  return node;
}

export function appendLabeledValue(container, label, value) {
  const row = el("div", { className: "metric-row" }, [
    el("span", { className: "metric-label", text: label }),
    el("span", { className: "metric-value", text: value ?? "-" }),
  ]);
  container.appendChild(row);
}

export function copyText(value) {
  if (!value) {
    return;
  }
  navigator.clipboard.writeText(String(value)).catch(() => {});
}
