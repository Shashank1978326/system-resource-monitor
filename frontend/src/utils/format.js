export function formatPercent(value, digits = 1) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(digits)}%`
    : "—";
}

export function formatBytes(value, digits = 1) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  if (value === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const index = Math.min(
    Math.floor(Math.log(Math.abs(value)) / Math.log(1024)),
    units.length - 1,
  );
  return `${(value / 1024 ** index).toFixed(digits)} ${units[index]}`;
}

export function formatRate(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  if (value < 1024) return `${value.toFixed(0)} B/s`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB/s`;
  return `${(value / 1024 ** 2).toFixed(2)} MB/s`;
}

export function formatFrequency(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${(value / 1000).toFixed(2)} GHz`
    : "—";
}

export function diskTotals(disk) {
  const partitions = disk?.partitions || [];
  const total = partitions.reduce((sum, item) => sum + (item.total_bytes || 0), 0);
  const used = partitions.reduce((sum, item) => sum + (item.used_bytes || 0), 0);
  const free = partitions.reduce((sum, item) => sum + (item.free_bytes || 0), 0);
  return {
    total,
    used,
    free,
    percent: total > 0 ? (used / total) * 100 : null,
  };
}

export function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}
