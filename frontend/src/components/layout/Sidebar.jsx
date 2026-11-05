import { NavLink } from "react-router-dom";
import Icon from "./Icons";

const navigation = [
  { label: "Dashboard", to: "/", icon: "dashboard", end: true },
  { label: "CPU", to: "/cpu", icon: "cpu" },
  { label: "Memory", to: "/memory", icon: "memory" },
  { label: "Disk", to: "/disk", icon: "disk" },
  { label: "Network", to: "/network", icon: "network" },
  { label: "Process monitor", to: "/processes", icon: "processes" },
  { label: "Historical analytics", to: "/history", icon: "history" },
  { label: "Anomaly detection", to: "/anomalies", icon: "anomaly" },
  { label: "Resource predictions", to: "/predictions", icon: "prediction" },
  { label: "Reports", to: "/reports", icon: "reports" },
  { label: "System information", to: "/system", icon: "system" },
  { label: "GPU information", to: "/gpu", icon: "gpu" },
  { label: "Settings", to: "/settings", icon: "settings" },
  { label: "Project showcase", to: "/showcase", icon: "showcase" },
];

export default function Sidebar({ open, onNavigate }) {
  return (
    <>
      {open && <button className="sidebar-backdrop" onClick={onNavigate} aria-label="Close navigation" />}
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
        <NavLink className="brand" to="/" onClick={onNavigate}>
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </span>
          <span className="brand-copy">
            <strong>Resource</strong>
            <small>MONITOR</small>
          </span>
        </NavLink>
        <div className="sidebar-label">WORKSPACE</div>
        <nav className="sidebar-nav" aria-label="Main navigation">
          {navigation.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={onNavigate}
              className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`}
            >
              <Icon name={item.icon} size={17} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="sidebar-status-dot" />
          <span>Local system monitor</span>
          <span className="sidebar-version">v0.1</span>
        </div>
      </aside>
    </>
  );
}
