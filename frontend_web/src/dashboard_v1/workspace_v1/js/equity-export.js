function cell(value) { return `"${String(value ?? "").replaceAll('"','""')}"`; }
function filenamePart(value) { return String(value ?? "unknown").replace(/[^A-Za-z0-9._-]+/g,"-").replace(/^-+|-+$/g,"") || "unknown"; }

export function buildEquitySeriesExport(payload, candidate) {
  if (!payload?.points?.length || !candidate?.listing_id || !payload.metric_id || !payload.series?.series_id) {
    throw new Error("Equity export requires a selected listing and returned Series");
  }
  if (payload.listing_id !== candidate.listing_id) throw new Error("Equity export listing differs from result");
  const snapshot = payload.snapshot || {};
  const header = ["universe","subject_type","listing_id","instrument_id","entity_id","display_name","external_code","exchange","market_jurisdiction","share_type","metric_id","series_id","adjustment_basis","requested_start","requested_end","economic_time","value","unit","currency","scale","time_role","release_id","release_hash","component_snapshot_id","source_observation_id"];
  const context = ["Equity","listing",candidate.listing_id,candidate.instrument_id,candidate.entity_id,candidate.display_name,candidate.external_code,candidate.exchange,candidate.market_jurisdiction,candidate.share_type,payload.metric_id,payload.series.series_id,payload.series.adjustment_basis || "unadjusted",payload.requested_interval?.start,payload.requested_interval?.end];
  const rows = payload.points.map(point => [...context,point.economic_time,point.value,point.unit,point.currency,point.scale,point.time_role,snapshot.release_id,snapshot.release_hash,snapshot.component_snapshot_id,point.source_observation_id].map(cell).join(","));
  return {
    filename: ["fr-equity",candidate.exchange,candidate.external_code,filenamePart(candidate.listing_id).slice(-16),filenamePart(payload.metric_id),payload.requested_interval?.start,payload.requested_interval?.end].map(filenamePart).join("-") + ".csv",
    csv: `\ufeff${[header.map(cell).join(","),...rows].join("\r\n")}\r\n`,
    rowCount: rows.length,
  };
}
