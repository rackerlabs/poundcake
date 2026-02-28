export function activateTab(tabId) {
  const tabs = document.querySelectorAll(".tab-btn");
  const panels = document.querySelectorAll(".panel");

  tabs.forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.tab === tabId);
  });

  panels.forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === `tab-${tabId}`);
  });
}

export function getIncidentOrderIdFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("incident_order_id");
  const parsed = Number(raw || 0);
  if (Number.isFinite(parsed) && parsed > 0) {
    return parsed;
  }
  return null;
}

export function setIncidentOrderIdInUrl(orderId = null) {
  const url = new URL(window.location.href);
  if (orderId && Number(orderId) > 0) {
    url.searchParams.set("incident_order_id", String(orderId));
  } else {
    url.searchParams.delete("incident_order_id");
  }
  window.history.replaceState({}, "", url.toString());
}
