import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { API_BASE_URL, getInitialMonitoringData } from "../services/api";
import MonitoringContext from "./monitoringStore";
const MAX_LIVE_POINTS = 60;
const HISTORY_POINTS_KEY = "srm-dashboard-history-points";

function readHistoryLimit() {
  const stored = Number(window.localStorage.getItem(HISTORY_POINTS_KEY));
  return [30, 60, 120].includes(stored) ? stored : MAX_LIVE_POINTS;
}

function websocketUrl() {
  const url = new URL("/ws/monitoring", API_BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

function mergeUpdate(snapshot, message) {
  if (!snapshot) return snapshot;
  const data = message.data;
  return {
    ...snapshot,
    timestamp: message.timestamp,
    cpu: { ...snapshot.cpu, cpu_usage_percent: data.cpu_percent },
    memory: { ...snapshot.memory, usage_percent: data.memory_percent },
    disk: snapshot.disk,
    network: {
      ...snapshot.network,
      download_speed_bytes_per_sec: data.network_download_bytes_per_sec,
      upload_speed_bytes_per_sec: data.network_upload_bytes_per_sec,
    },
    liveDiskPercent: data.disk_percent,
  };
}

function chartPoint(snapshot, timestamp) {
  return {
    time: new Date(timestamp).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }),
    cpu: snapshot.cpu?.cpu_usage_percent ?? null,
    memory: snapshot.memory?.usage_percent ?? null,
    disk: snapshot.liveDiskPercent ?? null,
    download: snapshot.network?.download_speed_bytes_per_sec ?? null,
    upload: snapshot.network?.upload_speed_bytes_per_sec ?? null,
  };
}

export function MonitoringProvider({ children }) {
  const [snapshot, setSnapshot] = useState(null);
  const [history, setHistory] = useState([]);
  const [connection, setConnection] = useState("connecting");
  const [backendReachable, setBackendReachable] = useState(null);
  const [connectionError, setConnectionError] = useState("");
  const [monitoringStatus, setMonitoringStatus] = useState(null);
  const [systemInfo, setSystemInfo] = useState(null);
  const [systemInfoError, setSystemInfoError] = useState("");
  const [historyPointLimit, setHistoryPointLimit] = useState(readHistoryLimit);
  const socketRef = useRef(null);
  const snapshotRef = useRef(null);
  const historyPointLimitRef = useRef(historyPointLimit);
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const mountedRef = useRef(false);
  const initialRequestRef = useRef(false);
  historyPointLimitRef.current = historyPointLimit;

  const applySnapshot = useCallback((nextSnapshot) => {
    snapshotRef.current = nextSnapshot;
    setSnapshot(nextSnapshot);
    setHistory((points) => [
      ...points,
      chartPoint(nextSnapshot, nextSnapshot.timestamp),
    ].slice(-historyPointLimitRef.current));
  }, []);

  useEffect(() => {
    window.localStorage.setItem(HISTORY_POINTS_KEY, String(historyPointLimit));
    setHistory((points) => points.slice(-historyPointLimit));
  }, [historyPointLimit]);

  useEffect(() => {
    mountedRef.current = true;
    let active = true;
    const loadInitialData = () => {
      if (initialRequestRef.current) return;
      initialRequestRef.current = true;
      getInitialMonitoringData().then((result) => {
        if (!active || !mountedRef.current) return;
        setBackendReachable(result.backendReachable);
        setConnectionError(result.error || "");
        setMonitoringStatus(result.status);
        setSystemInfo(result.systemInfo);
        setSystemInfoError(result.systemInfoError || "");
        if (
          result.snapshot &&
          (!snapshotRef.current ||
            Date.parse(result.snapshot.timestamp) >=
              Date.parse(snapshotRef.current.timestamp))
        ) {
          applySnapshot(result.snapshot);
        }
      }).finally(() => {
        initialRequestRef.current = false;
      });
    };
    loadInitialData();

    const connect = () => {
      if (!active || socketRef.current) return;
      setConnection((current) => (current === "connected" ? current : "connecting"));
      let socket;
      try {
        socket = new WebSocket(websocketUrl());
      } catch {
        setConnection("disconnected");
        setConnectionError("Could not open a connection to the monitoring service.");
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        if (!active) {
          socket.close();
          return;
        }
        reconnectAttemptRef.current = 0;
        setConnection("connected");
        setBackendReachable(true);
        setConnectionError("");
        if (!snapshotRef.current) loadInitialData();
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (
            message?.type !== "resource_update" ||
            typeof message.timestamp !== "string" ||
            !Number.isFinite(Date.parse(message.timestamp)) ||
            !message.data ||
            typeof message.data !== "object" ||
            Array.isArray(message.data)
          ) {
            throw new Error("Unexpected monitoring update format");
          }
          const metrics = [
            message.data.cpu_percent,
            message.data.memory_percent,
            message.data.disk_percent,
            message.data.network_download_bytes_per_sec,
            message.data.network_upload_bytes_per_sec,
          ];
          if (!metrics.every((value) => value === null || (typeof value === "number" && Number.isFinite(value)))) {
            throw new Error("Monitoring update contains invalid metric values");
          }
          setConnectionError("");
          if (!snapshotRef.current) {
            loadInitialData();
            return;
          }
          const next = mergeUpdate(snapshotRef.current, message);
          if (next) {
            snapshotRef.current = next;
            setSnapshot(next);
            setHistory((points) => [
              ...points,
              chartPoint(next, message.timestamp),
            ].slice(-historyPointLimitRef.current));
          }
        } catch {
          setConnectionError("The backend sent an unreadable monitoring update.");
        }
      };
      socket.onerror = () => {
        setBackendReachable(false);
        setConnectionError(
          "The live monitoring connection failed. Check that the backend is running.",
        );
      };
      socket.onclose = () => {
        if (socketRef.current === socket) socketRef.current = null;
        if (!active) return;
        setConnection("disconnected");
        setBackendReachable(false);
        scheduleReconnect();
      };
    };

    function scheduleReconnect() {
      if (!active || reconnectTimerRef.current) return;
      const delay = Math.min(1000 * 2 ** reconnectAttemptRef.current, 15000);
      reconnectAttemptRef.current += 1;
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, delay);
    }

    connect();
    return () => {
      active = false;
      mountedRef.current = false;
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [applySnapshot]);

  const value = useMemo(
    () => ({
      snapshot,
      history,
      connection,
      backendReachable,
      connectionError,
      monitoringStatus,
      systemInfo,
      systemInfoError,
      historyPointLimit,
      setHistoryPointLimit,
    }),
    [
      snapshot,
      history,
      connection,
      backendReachable,
      connectionError,
      monitoringStatus,
      systemInfo,
      systemInfoError,
      historyPointLimit,
    ],
  );
  return (
    <MonitoringContext.Provider value={value}>
      {children}
    </MonitoringContext.Provider>
  );
}
