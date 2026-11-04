import {escapeHtml} from "./components.js";
import {state} from "./state.js";
import {normalizeRoute, resolveRoute} from "./view-registry.js";

let renderRevision = 0;
let lastRoute = "";

function setActiveNavigation(route) {
  document.querySelectorAll("[data-route]").forEach((item) => {
    const active = item.dataset.route === route && item.id !== "nav-settings";
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  for (const area of ["data", "research", "settings"]) {
    document.querySelector(`[data-nav-section="${area}"]`)?.classList.toggle("current-section", route.startsWith(`/${area}`));
  }
  if (route === "/advanced") document.getElementById("advanced-nav").open = true;
}

export function closeNavigation() {
  document.body.classList.remove("nav-open");
  document.getElementById("nav-scrim").hidden = true;
  document.getElementById("nav-open").setAttribute("aria-expanded", "false");
}

export async function renderCurrentRoute({preservePosition = false} = {}) {
  const revision = ++renderRevision;
  const definition = resolveRoute(window.location.hash);
  if (window.location.hash !== `#${definition.path}`) window.history.replaceState(null, "", `#${definition.path}`);
  const routeChanged = lastRoute !== definition.path;
  const readingPosition = preservePosition || !routeChanged ? window.scrollY : 0;
  if (state.activeRoute !== definition.path) state.routeVisitRevision += 1;
  state.activeRoute = definition.path;
  setActiveNavigation(definition.path);
  const titles = state.language === "en" ? {"/home":"Home","/data":"Data","/data/fund/china-public":"Funds","/data/equity/china":"Equities","/research/statistics":"Statistics","/research/modeling":"Modeling","/settings/data-update":"Data Update","/settings/data-status":"Data Status","/advanced":"Advanced"} : {"/home":"首页","/data":"数据","/data/fund/china-public":"基金","/data/equity/china":"股票","/research/statistics":"统计分析","/research/modeling":"建模","/settings/data-update":"更新数据","/settings/data-status":"数据状态","/advanced":"高级"};
  document.title = `${titles[definition.path] || definition.title} · Financial Research`;
  const main = document.getElementById("workspace-main");
  if (routeChanged) main.innerHTML = `<div class="loading-state">${state.language === "en" ? "Opening…" : "正在打开…"}</div>`;
  try {
    const render = await definition.load();
    if (revision !== renderRevision) return;
    await render();
    if (revision !== renderRevision) return;
    lastRoute = definition.path;
    window.scrollTo({top: readingPosition, behavior: "instant"});
    if (routeChanged) main.focus({preventScroll: true});
  } catch (error) {
    if (revision !== renderRevision) return;
    main.innerHTML = `<div class="page"><div class="risk" role="alert">${state.language === "en" ? "This page could not be opened." : "无法打开此页面。"}</div><details class="technical-detail"><summary>${state.language === "en" ? "Technical details" : "技术详情"}</summary><code>${escapeHtml(error?.message || error)}</code></details></div>`;
  }
}

export function navigate(route) {
  const normalized = normalizeRoute(route);
  if (window.location.hash === `#${normalized}`) renderCurrentRoute({preservePosition: true});
  else window.location.hash = normalized;
}

export function startNavigation() {
  document.getElementById("nav-open").addEventListener("click", () => {
    document.body.classList.add("nav-open");
    document.getElementById("nav-scrim").hidden = false;
    document.getElementById("nav-open").setAttribute("aria-expanded", "true");
  });
  document.getElementById("nav-close").addEventListener("click", closeNavigation);
  document.getElementById("nav-scrim").addEventListener("click", closeNavigation);
  document.querySelectorAll(".app-rail a").forEach((link) => link.addEventListener("click", closeNavigation));
  window.addEventListener("hashchange", () => {closeNavigation(); renderCurrentRoute();});
  if (!window.location.hash) window.location.replace("#/home");
  else renderCurrentRoute();
}
