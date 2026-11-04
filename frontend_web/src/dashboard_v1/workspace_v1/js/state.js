export const state = {
  language: "zh",
  activeRoute: "/home",
  routeVisitRevision: 0,
  readiness: null,
  platformHealth: null,
  configurationReadError: null,
  capabilityCatalog: null,
  configuration: null,
  lifecycle: {
    loading: false,
    error: null,
    revision: 0,
    observedAt: null,
    readback: null,
    pendingScopes: {},
    pendingConfiguredUpdate: false,
  },
};

const lifecycleListeners = new Set();

export function setLanguage(language) {
  state.language = language === "en" ? "en" : "zh";
}

export function captureRouteVisit(path) {
  return {path, revision: state.routeVisitRevision};
}

export function ownsRouteVisit(visit) {
  return visit?.path === state.activeRoute && visit.revision === state.routeVisitRevision;
}

export function isReady(capabilityId) {
  return state.readiness?.checks?.[capabilityId]?.status === "ready";
}

export function subscribeLifecycle(listener) {
  lifecycleListeners.add(listener);
  return () => lifecycleListeners.delete(listener);
}

export function setLifecycleState(patch = {}) {
  state.lifecycle = {...state.lifecycle, ...patch};
  lifecycleListeners.forEach((listener) => {
    try { listener(state.lifecycle); } catch { /* presentation subscribers are non-authoritative */ }
  });
  return state.lifecycle;
}
