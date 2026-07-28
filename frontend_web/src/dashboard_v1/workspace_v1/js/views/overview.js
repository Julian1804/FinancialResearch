import{setTaskBridgeMode}from"../ai-bridge.js";
import{escapeHtml}from"../components.js";
import{tx}from"../i18n.js";

export function renderOverview(){
  setTaskBridgeMode("overview");
  const t=tx("overview");
  document.getElementById("workspace-main").innerHTML=`<div class="page overview-page">
    <section class="product-section catalog-hero">
      <div class="section-head">
        <div>
          <div class="eyebrow">${escapeHtml(t.kicker)}</div>
          <h1>${escapeHtml(t.title)}</h1>
          <p>${escapeHtml(t.subtitle)}</p>
        </div>
      </div>
      <div class="overview-card-grid">
        ${t.cards.map(([title,body])=>`<article class="card overview-card">
          <h3>${escapeHtml(title)}</h3>
          <p>${escapeHtml(body)}</p>
        </article>`).join("")}
      </div>
    </section>
  </div>`;
}
