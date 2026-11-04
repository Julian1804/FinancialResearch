import {workspaceApi} from "./api.js";
import {refreshProductLifecycle} from "./lifecycle.js";
import {renderCurrentRoute, startNavigation} from "./navigation.js";
import {setLanguage, state, subscribeLifecycle} from "./state.js";

let booting = true;
let lifecycleRenderTimer = null;

function updateLanguageChrome() {
  const language = state.language;
  document.documentElement.lang = language === "en" ? "en" : "zh-CN";
  document.querySelectorAll("[data-language]").forEach((button) => button.classList.toggle("active", button.dataset.language === language));
  document.querySelectorAll("[data-label-zh]").forEach((node) => {
    node.textContent = language === "en" ? node.dataset.labelEn : node.dataset.labelZh;
  });
  document.getElementById("nav-open").setAttribute("aria-label", language === "en" ? "Open navigation" : "打开导航");
  document.getElementById("nav-close").setAttribute("aria-label", language === "en" ? "Close navigation" : "关闭导航");
}

function bindLanguageToggle() {
  const saved = localStorage.getItem("fr_workspace_language");
  setLanguage(saved === "en" ? "en" : "zh");
  updateLanguageChrome();
  document.querySelectorAll("[data-language]").forEach((button) => button.addEventListener("click", () => {
    setLanguage(button.dataset.language);
    localStorage.setItem("fr_workspace_language", state.language);
    updateLanguageChrome();
    renderCurrentRoute({preservePosition: true});
  }));
}

async function loadProductContext() {
  const [product, capabilities] = await Promise.all([
    refreshProductLifecycle().catch((error) => {
      state.platformHealth = null;
      state.configurationReadError = error;
      return {readiness: {status: "not_ready", checks: {}}, configuration: state.configuration, lifecycle: state.lifecycle.readback};
    }),
    workspaceApi.system.capabilities().catch(() => ({capabilities: []})),
  ]);
  state.readiness = product.readiness || {status: "not_ready", checks: {}};
  state.capabilityCatalog = capabilities || {capabilities: []};
  booting = false;
  renderCurrentRoute();
}

subscribeLifecycle(() => {
  if (booting || lifecycleRenderTimer) return;
  lifecycleRenderTimer = setTimeout(() => {
    lifecycleRenderTimer = null;
    renderCurrentRoute();
  }, 0);
});

window.addEventListener("focus", () => { refreshProductLifecycle().catch(() => {}); });
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refreshProductLifecycle().catch(() => {});
});

bindLanguageToggle();
startNavigation();
loadProductContext();
