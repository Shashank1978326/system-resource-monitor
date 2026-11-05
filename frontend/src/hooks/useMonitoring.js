import { useContext } from "react";
import MonitoringContext from "../context/monitoringStore";

export default function useMonitoring() {
  const context = useContext(MonitoringContext);
  if (!context) throw new Error("useMonitoring must be used inside MonitoringProvider");
  return context;
}
