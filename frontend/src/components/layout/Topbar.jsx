import { Link } from "react-router-dom";
import useMonitoring from "../../hooks/useMonitoring";
import useTheme from "../../hooks/useTheme";
import Icon from "./Icons";

export default function Topbar({ onMenu }) {
  const { backendReachable, connection, systemInfo } = useMonitoring();
  const { theme, toggleTheme } = useTheme();
  const backendLabel =
    backendReachable === false
      ? "Backend unavailable"
      : backendReachable === true
        ? "Backend online"
        : "Connecting";

  return (
    <header className="topbar">
      <button className="icon-button mobile-menu" onClick={onMenu} aria-label="Open navigation">
        <Icon name="menu" />
      </button>
      <div className="topbar-title">
        <span className="topbar-product">System Resource Monitor</span>
        <span className="topbar-context">Overview</span>
      </div>
      <div className="topbar-actions">
        <div className="connection-pills">
          <span className={`connection-pill ${backendReachable === false ? "is-offline" : ""}`}>
            <span className={`status-dot ${backendReachable === false ? "status-dot-error" : ""}`} />
            {backendLabel}
          </span>
          <span className={`connection-pill connection-secondary ${connection === "connected" ? "is-live" : "is-offline"}`}>
            <span className={`status-dot ${connection === "connected" ? "status-dot-live" : "status-dot-error"}`} />
            {connection === "connected" ? "Live updates" : "Live disconnected"}
          </span>
        </div>
        <div className="host-pill" title={systemInfo?.operating_system || ""}>
          <span className="host-avatar">{systemInfo?.hostname?.slice(0, 1)?.toUpperCase() || "S"}</span>
          <span>{systemInfo?.hostname || "This system"}</span>
        </div>
        <Link to="/showcase" className="topbar-showcase-link" title="Open Project Showcase & Docs">
          <Icon name="showcase" size={15} />
          <span>Showcase</span>
        </Link>
        <button
          className="icon-button theme-toggle"
          onClick={toggleTheme}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          title="Toggle theme"
        >
          <Icon name={theme === "dark" ? "sun" : "moon"} size={17} />
        </button>
      </div>
    </header>
  );
}
