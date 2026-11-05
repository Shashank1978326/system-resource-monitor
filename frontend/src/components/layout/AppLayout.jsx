import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";

const pageTitles = {
  "/": "Dashboard",
  "/cpu": "CPU",
  "/memory": "Memory",
  "/disk": "Disk",
  "/network": "Network",
  "/processes": "Process monitor",
  "/history": "Historical analytics",
  "/anomalies": "Anomaly Detection",
  "/predictions": "Resource Predictions",
  "/reports": "Diagnostic Reports",
  "/system": "System information",
  "/gpu": "GPU information",
  "/settings": "Settings",
};

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  const title = pageTitles[location.pathname] || "Dashboard";

  return (
    <div className="app-shell">
      <Sidebar open={sidebarOpen} onNavigate={() => setSidebarOpen(false)} />
      <div className="workspace">
        <Topbar onMenu={() => setSidebarOpen(true)} />
        <main className="page-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">SYSTEM OVERVIEW</div>
              <h1>{title}</h1>
            </div>
            <span className="page-heading-note">Resource telemetry</span>
          </div>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
