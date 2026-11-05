import { Link } from "react-router-dom";
import LiveChart from "../charts/LiveChart";

export default function MetricCard({
  title,
  icon,
  value,
  description,
  metric,
  history,
  metrics,
  unit = "%",
  to,
  children,
}) {
  return (
    <Link className="metric-card" to={to} aria-label={`View ${title} details`}>
      <div className="metric-card-header">
        <div className="metric-title">
          <span className={`metric-icon metric-icon-${metric}`} aria-hidden="true">
            {icon}
          </span>
          <span>{title}</span>
        </div>
        <span className="card-arrow" aria-hidden="true">
          ↗
        </span>
      </div>
      <div className="metric-reading">
        <strong>{value}</strong>
        <span>{description}</span>
      </div>
      <LiveChart data={history} metric={metric} metrics={metrics} unit={unit} />
      <div className="metric-card-footer">{children}</div>
    </Link>
  );
}
