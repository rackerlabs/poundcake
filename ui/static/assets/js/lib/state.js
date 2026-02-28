export const appState = {
  activeTab: "dashboard",
  currentIncidentOrderId: null,
  alertsPollTimer: null,
  settings: null,
};

export function setActiveTab(tabId) {
  appState.activeTab = tabId;
}

export function setCurrentIncidentOrderId(orderId) {
  appState.currentIncidentOrderId = orderId;
}

export function startAlertsPolling(callback, intervalMs = 5000) {
  stopAlertsPolling();
  appState.alertsPollTimer = window.setInterval(callback, intervalMs);
}

export function stopAlertsPolling() {
  if (appState.alertsPollTimer) {
    clearInterval(appState.alertsPollTimer);
    appState.alertsPollTimer = null;
  }
}
