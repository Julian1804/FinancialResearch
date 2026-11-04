# FR Research Workspace

This dependency-free frontend is the supported ordinary-user shell for the
published Fund + China Equity V1. The supported local gateway serves only the
current shell, its active modules, and the standalone Morningstar credential
panel. Retained prototype pages and JavaScript remain source history, not
ordinary product routes.

## Current Routes

- `#/home`: serving status and the two published V1 financial-data capabilities.
- `#/data`: truthful catalog/availability boundary; no inferred Universe counts.
- `#/data/fund/china-public`: release-pinned Fund object, relationship, lifecycle,
  and bounded Series workflow, including explicit validated-review selection.
- `#/data/equity/china`: release-pinned exact exchange/code/alias-date resolution
  and bounded unadjusted daily Series. The lack of name/general discovery is
  explicit.
- `#/tools`: local and review capability disclosure. It does not promote those
  routes to V1 serving authority.

Modeling, simulation, dashboards, projects, application registries, and the
permanent AI/result rail are not current product navigation. Their retained code
does not establish current usability or authority.

## Implementation Boundaries

- Browser networking is centralized in `workspace_v1/js/api.js` and uses only
  current backend routes.
- `state.js` owns shell state only. Fund and China Equity workflows own their
  page state.
- Every financial query is bound to one immutable release/snapshot and response
  bindings are checked before display.
- Query ranges and row limits remain explicit. Normal errors preserve safe code,
  request ID, and operation ID context without displaying local paths or raw
  payloads.
- Update actions run only after explicit user input and do not silently switch
  the release pinned in the current research interaction.
- Future Universes extend Financial Data as peer capabilities with their own
  identity, lifecycle, Series, availability, release, and error contracts.

Independent browser, responsive, accessibility, and ordinary-user operability
acceptance remains a separate stage. This code baseline does not claim that
acceptance result.

`legacy_streamlit_used = false`.
