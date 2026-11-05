export const ranges = [
  ["5m", "5 minutes", 5 * 60],
  ["15m", "15 minutes", 15 * 60],
  ["30m", "30 minutes", 30 * 60],
  ["1h", "1 hour", 60 * 60],
  ["6h", "6 hours", 6 * 60 * 60],
  ["12h", "12 hours", 12 * 60 * 60],
  ["24h", "24 hours", 24 * 60 * 60],
  ["7d", "7 days", 7 * 24 * 60 * 60],
];

export const intervals = [
  ["1m", "1 minute", 60],
  ["5m", "5 minutes", 5 * 60],
  ["15m", "15 minutes", 15 * 60],
  ["1h", "1 hour", 60 * 60],
];

export function isOverLimit(range, interval) {
  const rangeSeconds = ranges.find(([key]) => key === range)?.[2] || 0;
  const intervalSeconds = intervals.find(([key]) => key === interval)?.[2] || 1;
  return Math.ceil(rangeSeconds / intervalSeconds) + 1 > 10000;
}
