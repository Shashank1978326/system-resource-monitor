import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const COLORS = {
  cpu: "#5577ec",
  memory: "#9b6bdf",
  disk: "#e1a344",
  download: "#2b9c84",
  upload: "#5478e8",
};

function ChartTooltip({ active, payload, label, unit = "%" }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <span>{label}</span>
      {payload.map((point) => (
        <strong key={point.dataKey} style={{ color: point.color }}>
          {typeof point.value === "number"
            ? unit === "%"
              ? `${point.name}: ${point.value.toFixed(1)}%`
              : `${point.name}: ${point.value.toFixed(1)} B/s`
            : `${point.name}: Unavailable`}
        </strong>
      ))}
    </div>
  );
}

export default function LiveChart({
  data = [],
  metric,
  metrics,
  unit = "%",
  height = 118,
  showAxis = false,
}) {
  const color = COLORS[metric] || COLORS.cpu;
  const series = metrics || [{ key: metric, color, label: metric }];
  return (
    <div className="chart-wrap" style={{ height }}>
      {data.length === 0 ? (
        <div className="chart-placeholder">Waiting for the first sample…</div>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 2, left: -28, bottom: 0 }}>
            <defs>
              <linearGradient id={`fill-${metric}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.2} />
                <stop offset="95%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid
              vertical={false}
              stroke="var(--chart-grid)"
              strokeDasharray="3 5"
            />
            {showAxis && (
              <>
                <XAxis
                  dataKey="time"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "var(--text-muted)", fontSize: 10 }}
                  minTickGap={30}
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "var(--text-muted)", fontSize: 10 }}
                  domain={unit === "%" ? [0, 100] : ["auto", "auto"]}
                  tickFormatter={(value) =>
                    unit === "%" ? `${value}%` : `${Math.round(value / 1024)}k`
                  }
                />
              </>
            )}
            <Tooltip content={<ChartTooltip unit={unit} />} />
            {series.map((item) => (
              <Area
                key={item.key}
                type="monotone"
                dataKey={item.key}
                name={item.label || item.key}
                stroke={item.color || COLORS[item.key] || color}
                strokeWidth={2}
                fill={series.length === 1 ? `url(#fill-${metric})` : "transparent"}
                connectNulls={false}
                isAnimationActive={false}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0 }}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
