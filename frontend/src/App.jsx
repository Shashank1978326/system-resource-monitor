import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/layout/AppLayout";
import { MonitoringProvider } from "./context/MonitoringContext";
import { ThemeProvider } from "./context/ThemeContext";
import CPU from "./pages/CPU";
import Dashboard from "./pages/Dashboard";
import Disk from "./pages/Disk";
import HistoricalAnalytics from "./pages/HistoricalAnalytics";
import Anomalies from "./pages/Anomalies";
import Predictions from "./pages/Predictions";
import Reports from "./pages/Reports";
import GpuInfo from "./pages/GpuInfo";
import Memory from "./pages/Memory";
import Network from "./pages/Network";
import Processes from "./pages/Processes";
import Settings from "./pages/Settings";
import SystemInfo from "./pages/SystemInfo";
import PortfolioShowcase from "./pages/PortfolioShowcase";

export default function App() {
  const isShowcaseHome = import.meta.env.VITE_LANDING_PAGE === "showcase";

  return (
    <ThemeProvider>
      <MonitoringProvider>
        <Routes>
          <Route path="/showcase" element={<PortfolioShowcase />} />
          {isShowcaseHome && (
            <>
              <Route path="/" element={<PortfolioShowcase />} />
              <Route path="/landing" element={<PortfolioShowcase />} />
            </>
          )}
          <Route element={<AppLayout />}>
            {!isShowcaseHome && <Route path="/" element={<Dashboard />} />}
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/cpu" element={<CPU />} />
            <Route path="/memory" element={<Memory />} />
            <Route path="/disk" element={<Disk />} />
            <Route path="/network" element={<Network />} />
            <Route path="/processes" element={<Processes />} />
            <Route path="/history" element={<HistoricalAnalytics />} />
            <Route path="/anomalies" element={<Anomalies />} />
            <Route path="/predictions" element={<Predictions />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/system" element={<SystemInfo />} />
            <Route path="/gpu" element={<GpuInfo />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </MonitoringProvider>
    </ThemeProvider>
  );
}
