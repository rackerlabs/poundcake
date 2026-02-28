import { setUnauthorizedHandler } from "./lib/api-client.js";
import { checkSession, logout, redirectToLogin } from "./lib/auth.js";
import {
  activateTab,
  getIncidentOrderIdFromUrl,
  setIncidentOrderIdInUrl,
} from "./lib/router.js";
import {
  appState,
  setActiveTab,
  setCurrentIncidentOrderId,
  startAlertsPolling,
  stopAlertsPolling,
} from "./lib/state.js";

import * as dashboardTab from "./tabs/dashboard.js";
import * as alertsTab from "./tabs/alerts.js";
import * as recipesTab from "./tabs/recipes.js";
import * as ingredientsTab from "./tabs/ingredients.js";
import * as incidentTab from "./tabs/incident.js";
import * as suppressionsTab from "./tabs/suppressions.js";
import * as ticketingTab from "./tabs/ticketing.js";
import * as prometheusTab from "./tabs/prometheus.js";
import * as historyTab from "./tabs/history.js";

const tabModules = {
  dashboard: dashboardTab,
  alerts: alertsTab,
  recipes: recipesTab,
  ingredients: ingredientsTab,
  incident: incidentTab,
  suppressions: suppressionsTab,
  ticketing: ticketingTab,
  prometheus: prometheusTab,
  history: historyTab,
};

function toastClass(type) {
  if (type === "success") return "toast success";
  if (type === "error") return "toast error";
  return "toast";
}

function notify(type, message, timeoutMs = 4200) {
  const wrap = document.getElementById("toast-wrap");
  if (!wrap) {
    return;
  }

  const toast = document.createElement("div");
  toast.className = toastClass(type);
  toast.textContent = message;
  wrap.appendChild(toast);

  window.setTimeout(() => {
    toast.remove();
  }, timeoutMs);
}

function confirmDialog(message) {
  const overlay = document.getElementById("confirm-overlay");
  const content = document.getElementById("confirm-message");
  const cancel = document.getElementById("confirm-cancel");
  const proceed = document.getElementById("confirm-proceed");

  if (!overlay || !content || !cancel || !proceed) {
    return Promise.resolve(false);
  }

  content.textContent = message;
  overlay.classList.add("is-open");

  return new Promise((resolve) => {
    const cleanup = () => {
      overlay.classList.remove("is-open");
      cancel.removeEventListener("click", onCancel);
      proceed.removeEventListener("click", onProceed);
      overlay.removeEventListener("click", onOverlayClick);
    };

    const onCancel = () => {
      cleanup();
      resolve(false);
    };

    const onProceed = () => {
      cleanup();
      resolve(true);
    };

    const onOverlayClick = (event) => {
      if (event.target.id === "confirm-overlay") {
        onCancel();
      }
    };

    cancel.addEventListener("click", onCancel);
    proceed.addEventListener("click", onProceed);
    overlay.addEventListener("click", onOverlayClick);
  });
}

async function refreshCurrentTab() {
  const module = tabModules[appState.activeTab];
  if (!module?.load) {
    return;
  }
  await module.load();
}

function updateAlertsPolling() {
  if (appState.activeTab !== "alerts") {
    stopAlertsPolling();
    return;
  }

  if (!alertsTab.isAutoRefreshEnabled()) {
    stopAlertsPolling();
    return;
  }

  startAlertsPolling(async () => {
    if (appState.activeTab === "alerts" && alertsTab.isAutoRefreshEnabled()) {
      try {
        await alertsTab.load();
      } catch (error) {
        notify("error", `Auto-refresh failed: ${error.message}`);
      }
    }
  });
}

async function switchTab(tabId) {
  if (!tabModules[tabId]) {
    return;
  }

  setActiveTab(tabId);
  activateTab(tabId);

  if (tabId !== "incident") {
    setIncidentOrderIdInUrl(appState.currentIncidentOrderId);
  }

  if (tabId === "incident" && !appState.currentIncidentOrderId) {
    updateAlertsPolling();
    return;
  }

  try {
    await refreshCurrentTab();
  } catch (error) {
    notify("error", error.message);
  }

  updateAlertsPolling();
}

async function handleLogout() {
  const ok = await confirmDialog("Are you sure you want to logout?");
  if (!ok) {
    return;
  }

  try {
    await logout();
  } catch {
    // ignore and continue redirect
  }
  redirectToLogin("/");
}

function wireTopLevelEvents() {
  document.querySelectorAll(".tab-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const tabId = button.dataset.tab;
      switchTab(tabId);
    });
  });

  document.getElementById("logout-btn")?.addEventListener("click", () => {
    handleLogout();
  });

  document.getElementById("alerts-auto-refresh")?.addEventListener("change", () => {
    updateAlertsPolling();
  });
}

async function bootstrap() {
  setUnauthorizedHandler(() => redirectToLogin());

  let session;
  try {
    session = await checkSession();
  } catch {
    redirectToLogin();
    return;
  }
  if (!session.authenticated) {
    redirectToLogin();
    return;
  }

  appState.settings = session.settings;

  const context = {
    notify,
    confirm: confirmDialog,
    switchTab,
    openIncident: (orderId) => incidentTab.open(orderId),
    setIncidentOrderId: (orderId) => {
      setCurrentIncidentOrderId(orderId);
      setIncidentOrderIdInUrl(orderId);
    },
    refreshDashboard: () => dashboardTab.load(),
  };

  Object.values(tabModules).forEach((module) => {
    if (typeof module.init === "function") {
      module.init(context);
    }
  });

  wireTopLevelEvents();

  const deepLinkOrderId = getIncidentOrderIdFromUrl();
  if (deepLinkOrderId) {
    setCurrentIncidentOrderId(deepLinkOrderId);
    await switchTab("incident");
    await incidentTab.load(deepLinkOrderId);
    return;
  }

  await switchTab("dashboard");
}

document.addEventListener("DOMContentLoaded", () => {
  bootstrap().catch((error) => {
    notify("error", `UI bootstrap failed: ${error.message}`);
    redirectToLogin();
  });
});
