export function latestReturnedPoint(points) {
  const rows = Array.isArray(points) ? points : [];
  return rows.reduce((latest, row) => (
    !latest || String(row?.economic_time || "") > String(latest?.economic_time || "") ? row : latest
  ), null);
}

export function latestReturnedLabel(payload, labels) {
  const point = latestReturnedPoint(payload?.points);
  return point?.economic_time || labels.noReturnedObservation;
}

export function relatedSeriesMetricId(relationship) {
  const attributes = relationship?.attributes || relationship?.relationship_attributes || {};
  return attributes.metric_id || attributes.series_metric_id || "";
}
