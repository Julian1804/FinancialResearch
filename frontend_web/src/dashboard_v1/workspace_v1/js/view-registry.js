export const productRoutes = [
  {path: "/home", area: "home", title: "Financial Research", load: async () => (await import("./views/overview.js")).renderOverview},
  {path: "/data", area: "data", title: "Financial Data", load: async () => (await import("./views/database-status.js")).renderDatabaseStatus},
  {path: "/data/fund/china-public", area: "fund", title: "China Public Fund", load: async () => (await import("./views/public-fund.js")).renderPublicFund},
  {path: "/data/equity/china", area: "equity", title: "China Equity", load: async () => (await import("./views/china-equity.js")).renderChinaEquity},
  {path: "/research/statistics", area: "research", title: "Statistics", load: async () => (await import("./views/comparative-series.js")).renderComparativeSeries},
  {path: "/research/modeling", area: "research", title: "Modeling", load: async () => (await import("./views/modeling-stage1.js")).renderModeling},
  {path: "/settings/data-update", area: "settings", title: "Data Update", load: async () => (await import("./views/data-update.js")).renderDataUpdate},
  {path: "/settings/data-status", area: "settings", title: "Data Status", load: async () => (await import("./views/data-status.js")).renderDataStatus},
  {path: "/advanced", area: "advanced", title: "Advanced", load: async () => (await import("./views/local-tools.js")).renderLocalTools},
];

export function normalizeRoute(value) {
  const raw = String(value || "").replace(/^#/, "").split("?")[0];
  const selected = raw.startsWith("/") ? raw : `/${raw}`;
  const path = ({"/research/comparative-series":"/research/statistics","/tools":"/advanced","/settings":"/settings/data-status"})[selected] || selected;
  return productRoutes.some((item) => item.path === path) ? path : "/home";
}

export function resolveRoute(value) {
  const path = normalizeRoute(value);
  return productRoutes.find((item) => item.path === path) || productRoutes[0];
}
