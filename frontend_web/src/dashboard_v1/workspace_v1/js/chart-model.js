export function buildTimeSeriesChartModel(points, maxSamplePoints = 320) {
  const valid = (points || []).map((row, sourceIndex) => ({
    row,
    sourceIndex,
    numericValue: Number(row?.value),
  })).filter((item) => Number.isFinite(item.numericValue));
  if (!valid.length) return null;

  const minPoint = valid.reduce((best, item) => item.numericValue < best.numericValue ? item : best);
  const maxPoint = valid.reduce((best, item) => item.numericValue > best.numericValue ? item : best);
  const selected = new Set([0, valid.length - 1, valid.indexOf(minPoint), valid.indexOf(maxPoint)]);
  const step = valid.length > maxSamplePoints ? Math.ceil(valid.length / maxSamplePoints) : 1;
  for (let index = 0; index < valid.length; index += step) selected.add(index);
  const sample = [...selected].sort((left, right) => left - right).map((index) => valid[index]);

  return {
    sample,
    firstPoint: valid[0],
    lastPoint: valid.at(-1),
    minPoint,
    maxPoint,
    minValue: minPoint.numericValue,
    maxValue: maxPoint.numericValue,
  };
}

export function chartPath(model, width, height) {
  if (!model?.sample?.length) return "";
  const spread = model.maxValue - model.minValue || 1;
  return model.sample.map((item, index) => {
    const x = Math.round(index * width / Math.max(model.sample.length - 1, 1));
    const y = Math.round(height - (item.numericValue - model.minValue) * height / spread);
    return `${index ? "L" : "M"} ${x} ${y}`;
  }).join(" ");
}
