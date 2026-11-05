import { useEffect, useState } from "react";
import Panel from "../components/common/Panel";
import { ErrorBanner } from "../components/common/StateMessage";
import useTheme from "../hooks/useTheme";
import useMonitoring from "../hooks/useMonitoring";
import {
  API_BASE_URL,
  errorMessage,
  getAlertThresholds,
  getAnomalySettings,
  getBatteryInfo,
  getTemperatureInfo,
  updateAlertThresholds,
  updateAnomalySettings,
} from "../services/api";
import Icon from "../components/layout/Icons";

const THRESHOLD_DEFAULTS = {
  cpu_warning_threshold_percent: 80,
  cpu_critical_threshold_percent: 90,
  ram_warning_threshold_percent: 80,
  ram_critical_threshold_percent: 90,
  disk_warning_threshold_percent: 80,
  disk_critical_threshold_percent: 90,
  temperature_warning_threshold_celsius: 80,
  temperature_critical_threshold_celsius: 90,
  battery_warning_threshold_percent: 20,
  battery_critical_threshold_percent: 10,
};

const RESOURCES = [
  ["CPU", "cpu_warning_threshold_percent", "cpu_critical_threshold_percent"],
  ["RAM", "ram_warning_threshold_percent", "ram_critical_threshold_percent"],
  ["Disk", "disk_warning_threshold_percent", "disk_critical_threshold_percent"],
  ["Temperature", "temperature_warning_threshold_celsius", "temperature_critical_threshold_celsius"],
  ["Battery", "battery_warning_threshold_percent", "battery_critical_threshold_percent"],
];

export default function Settings() {
  const { preference, setPreference } = useTheme();
  const { historyPointLimit, setHistoryPointLimit } = useMonitoring();
  const [thresholds, setThresholds] = useState(THRESHOLD_DEFAULTS);
  const [thresholdLoading, setThresholdLoading] = useState(true);
  const [thresholdSaving, setThresholdSaving] = useState(false);
  const [thresholdError, setThresholdError] = useState("");
  const [thresholdMessage, setThresholdMessage] = useState("");
  const [temperatureAvailability, setTemperatureAvailability] = useState(null);
  const [temperatureStatusError, setTemperatureStatusError] = useState("");
  const [batteryAvailability, setBatteryAvailability] = useState(null);
  const [batteryStatusError, setBatteryStatusError] = useState("");
  const [anomalyConfig, setAnomalyConfig] = useState({
    enabled: true,
    min_samples: 20,
    z_score_threshold: 3.0,
    window_size: 60,
  });
  const [anomalyLoading, setAnomalyLoading] = useState(true);
  const [anomalySaving, setAnomalySaving] = useState(false);
  const [anomalyError, setAnomalyError] = useState("");
  const [anomalyMessage, setAnomalyMessage] = useState("");

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    getAlertThresholds({ signal: controller.signal })
      .then((result) => {
        if (active) setThresholds(result);
      })
      .catch((error) => {
        if (active && !controller.signal.aborted) {
          setThresholdError(errorMessage(error));
        }
      })
      .finally(() => {
        if (active) setThresholdLoading(false);
      });
    getTemperatureInfo({ signal: controller.signal })
      .then((result) => {
        if (active) {
          setTemperatureAvailability(result);
          setTemperatureStatusError("");
        }
      })
      .catch((error) => {
        if (active && !controller.signal.aborted) {
          setTemperatureStatusError(errorMessage(error));
        }
      });
    getBatteryInfo({ signal: controller.signal })
      .then((result) => {
        if (active) {
          setBatteryAvailability(result);
          setBatteryStatusError("");
        }
      })
      .catch((error) => {
        if (active && !controller.signal.aborted) {
          setBatteryStatusError(errorMessage(error));
        }
      });
    getAnomalySettings({ signal: controller.signal })
      .then((result) => {
        if (active) setAnomalyConfig(result);
      })
      .catch((error) => {
        if (active && !controller.signal.aborted) {
          setAnomalyError(errorMessage(error));
        }
      })
      .finally(() => {
        if (active) setAnomalyLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  async function saveThresholds(event) {
    event.preventDefault();
    for (const [resource, warningKey, criticalKey] of RESOURCES) {
      const warning = Number(thresholds[warningKey]);
      const critical = Number(thresholds[criticalKey]);
      const isTemperature = resource === "Temperature";
      const isBattery = resource === "Battery";

      if (isBattery) {
        if (
          !Number.isFinite(warning) ||
          !Number.isFinite(critical) ||
          warning < 0 ||
          warning > 100 ||
          critical < 0 ||
          critical > 100 ||
          critical >= warning
        ) {
          setThresholdError(
            "Battery critical threshold must be lower than warning threshold, and both must be between 0% and 100%.",
          );
          return;
        }
      } else if (
        !Number.isFinite(warning) ||
        !Number.isFinite(critical) ||
        warning < (isTemperature ? 0 : 1) ||
        (!isTemperature && warning > 100) ||
        critical < (isTemperature ? 0 : 1) ||
        (!isTemperature && critical > 100) ||
        warning >= critical
      ) {
        setThresholdError(
          isTemperature
            ? "Temperature thresholds must be finite and non-negative, with warning lower than critical."
            : `${resource} thresholds must be between 1% and 100%, with warning lower than critical.`,
        );
        return;
      }
    }
    setThresholdSaving(true);
    setThresholdError("");
    setThresholdMessage("");
    try {
      const saved = await updateAlertThresholds(
        Object.fromEntries(
          Object.entries(thresholds).map(([key, value]) => [key, Number(value)]),
        ),
      );
      setThresholds(saved);
      setThresholdMessage("Alert thresholds saved and applied.");
    } catch (error) {
      setThresholdError(errorMessage(error));
    } finally {
      setThresholdSaving(false);
    }
  }

  async function saveAnomalyConfig(event) {
    event.preventDefault();
    const minSamples = Number(anomalyConfig.min_samples);
    const zScore = Number(anomalyConfig.z_score_threshold);
    const windowSize = Number(anomalyConfig.window_size);

    if (!Number.isInteger(minSamples) || minSamples < 2) {
      setAnomalyError("Minimum baseline samples must be an integer of at least 2.");
      return;
    }
    if (!Number.isFinite(zScore) || zScore <= 0) {
      setAnomalyError("Z-score sensitivity threshold must be a positive number.");
      return;
    }
    if (!Number.isInteger(windowSize) || windowSize < minSamples) {
      setAnomalyError("Rolling window size must be an integer greater than or equal to minimum samples.");
      return;
    }
    if (windowSize > 10000) {
      setAnomalyError("Rolling window size must not exceed 10,000.");
      return;
    }

    setAnomalySaving(true);
    setAnomalyError("");
    setAnomalyMessage("");
    try {
      const saved = await updateAnomalySettings({
        enabled: Boolean(anomalyConfig.enabled),
        min_samples: minSamples,
        z_score_threshold: zScore,
        window_size: windowSize,
      });
      setAnomalyConfig(saved);
      setAnomalyMessage("Anomaly detection settings saved and applied.");
    } catch (error) {
      setAnomalyError(errorMessage(error));
    } finally {
      setAnomalySaving(false);
    }
  }

  return (
    <div className="settings-grid">
      <Panel title="Appearance" subtitle="Choose how the dashboard looks on this device">
        <div className="theme-options" role="group" aria-label="Theme preference">
          {[
            ["light", "Light", "sun"],
            ["dark", "Dark", "moon"],
            ["system", "System", "system"],
          ].map(([value, label, icon]) => (
            <button
              className={`theme-option ${preference === value ? "theme-option-selected" : ""}`}
              key={value}
              onClick={() => setPreference(value)}
              aria-pressed={preference === value}
            >
              <span><Icon name={icon === "system" ? "dashboard" : icon} size={19} /></span>
              <strong>{label}</strong>
              <small>{value === "system" ? "Follow device" : `${label} appearance`}</small>
            </button>
          ))}
        </div>
      </Panel>
      <Panel title="Dashboard preferences" subtitle="Local display options; monitoring remains driven by the backend">
        <label className="setting-row" htmlFor="history-points">
          <span><strong>Live chart history</strong><small>Number of recent WebSocket samples shown in dashboard charts</small></span>
          <select id="history-points" value={historyPointLimit} onChange={(event) => setHistoryPointLimit(Number(event.target.value))}>
            <option value={30}>30 samples</option>
            <option value={60}>60 samples</option>
            <option value={120}>120 samples</option>
          </select>
        </label>
        <div className="setting-note">
          Live charts receive updates at the interval configured by the backend. The dashboard does not poll resource endpoints.
        </div>
      </Panel>
      <Panel
        title="Resource alert thresholds"
        subtitle="Changes are saved to the backend and applied on the next monitoring sample"
        className="alert-threshold-panel"
      >
        <ErrorBanner message={thresholdError} />
        {thresholdLoading ? (
          <p className="setting-note">Loading saved alert thresholds…</p>
        ) : (
          <form onSubmit={saveThresholds}>
            <div className="threshold-grid">
              {RESOURCES.map(([resource, warningKey, criticalKey]) => (
                <fieldset className="threshold-resource" key={resource}>
                  <legend>{resource}</legend>
                  <label>
                    <span>Warning ({resource === "Temperature" ? "°C" : "%"})</span>
                    <input
                      type="number"
                      min={resource === "Temperature" || resource === "Battery" ? "0" : "1"}
                      max={resource === "Temperature" ? undefined : "100"}
                      step="0.1"
                      required
                      value={thresholds[warningKey]}
                      onChange={(event) => {
                        setThresholds((current) => ({
                          ...current,
                          [warningKey]: event.target.value,
                        }));
                        setThresholdError("");
                        setThresholdMessage("");
                      }}
                    />
                  </label>
                  <label>
                    <span>Critical ({resource === "Temperature" ? "°C" : "%"})</span>
                    <input
                      type="number"
                      min={resource === "Temperature" || resource === "Battery" ? "0" : "1"}
                      max={resource === "Temperature" ? undefined : "100"}
                      step="0.1"
                      required
                      value={thresholds[criticalKey]}
                      onChange={(event) => {
                        setThresholds((current) => ({
                          ...current,
                          [criticalKey]: event.target.value,
                        }));
                        setThresholdError("");
                        setThresholdMessage("");
                      }}
                    />
                  </label>
                </fieldset>
              ))}
            </div>
            <p className="setting-note" role="status">
              {temperatureStatusError
                ? `Temperature sensor status unavailable: ${temperatureStatusError}`
                : temperatureAvailability?.availability === "available"
                  ? `${temperatureAvailability.sensors.filter((sensor) => sensor.current_celsius !== null).length} temperature sensor reading(s) currently available.`
                  : temperatureAvailability
                    ? `Temperature alerts are configured but inactive: ${temperatureAvailability.message || "no usable sensors are available"}`
                    : "Checking temperature sensor availability…"}
            </p>
            <p className="setting-note" role="status">
              {batteryStatusError
                ? `Battery status unavailable: ${batteryStatusError}`
                : batteryAvailability?.availability === "available"
                  ? `Battery hardware detected (${batteryAvailability.percentage !== null ? `${batteryAvailability.percentage}%` : "percentage unavailable"}, ${batteryAvailability.charging_state || "unknown state"}). Alerts trigger when discharging.`
                  : batteryAvailability
                    ? `Battery alerts are configured but inactive: ${batteryAvailability.message || "no battery hardware detected"}.`
                    : "Checking battery availability…"}
            </p>
            <div className="threshold-form-footer">
              <span className="setting-note" role="status">
                {thresholdMessage || "For CPU/RAM/Disk/Temp, warning must be lower than critical. For Battery, critical must be lower than warning."}
              </span>
              <button className="primary-button" type="submit" disabled={thresholdSaving}>
                {thresholdSaving ? "Saving…" : "Save thresholds"}
              </button>
            </div>
          </form>
        )}
      </Panel>
      <Panel
        title="Anomaly detection configuration"
        subtitle="Configure rolling baseline sample window and statistical Z-score sensitivity"
        className="anomaly-config-panel"
      >
        <ErrorBanner message={anomalyError} />
        {anomalyLoading ? (
          <p className="setting-note">Loading anomaly detection settings…</p>
        ) : (
          <form onSubmit={saveAnomalyConfig}>
            <label className="setting-row">
              <span>
                <strong>Detection engine</strong>
                <small>Enable statistical anomaly detection across CPU, RAM, disk, and network</small>
              </span>
              <input
                type="checkbox"
                checked={anomalyConfig.enabled}
                onChange={(event) => {
                  setAnomalyConfig((current) => ({
                    ...current,
                    enabled: event.target.checked,
                  }));
                  setAnomalyError("");
                  setAnomalyMessage("");
                }}
              />
            </label>
            <div className="threshold-grid" style={{ marginTop: "12px" }}>
              <fieldset className="threshold-resource">
                <legend>Baseline window</legend>
                <label>
                  <span>Minimum baseline samples</span>
                  <input
                    type="number"
                    min="2"
                    max="10000"
                    step="1"
                    required
                    value={anomalyConfig.min_samples}
                    onChange={(event) => {
                      setAnomalyConfig((current) => ({
                        ...current,
                        min_samples: event.target.value,
                      }));
                      setAnomalyError("");
                      setAnomalyMessage("");
                    }}
                  />
                </label>
                <label>
                  <span>Rolling window size</span>
                  <input
                    type="number"
                    min="2"
                    max="10000"
                    step="1"
                    required
                    value={anomalyConfig.window_size}
                    onChange={(event) => {
                      setAnomalyConfig((current) => ({
                        ...current,
                        window_size: event.target.value,
                      }));
                      setAnomalyError("");
                      setAnomalyMessage("");
                    }}
                  />
                </label>
              </fieldset>
              <fieldset className="threshold-resource">
                <legend>Sensitivity</legend>
                <label>
                  <span>Z-score sensitivity threshold</span>
                  <input
                    type="number"
                    min="0.1"
                    max="50"
                    step="0.1"
                    required
                    value={anomalyConfig.z_score_threshold}
                    onChange={(event) => {
                      setAnomalyConfig((current) => ({
                        ...current,
                        z_score_threshold: event.target.value,
                      }));
                      setAnomalyError("");
                      setAnomalyMessage("");
                    }}
                  />
                </label>
                <p className="setting-note" style={{ margin: "4px 0 0 0" }}>
                  Readings with Z-score ≥ threshold trigger Warning; Z-score ≥ 1.5× threshold trigger Critical.
                </p>
              </fieldset>
            </div>
            <div className="threshold-form-footer">
              <span className="setting-note" role="status">
                {anomalyMessage || "Defaults: minimum 20 samples, Z-score threshold 3.0, window size 60 samples."}
              </span>
              <button className="primary-button" type="submit" disabled={anomalySaving}>
                {anomalySaving ? "Saving…" : "Save anomaly settings"}
              </button>
            </div>
          </form>
        )}
      </Panel>
      <Panel title="Backend connection" subtitle="API address used by the dashboard">
        <div className="backend-address">
          <span className="backend-address-icon"><Icon name="network" /></span>
          <div><small>API base URL</small><strong>{API_BASE_URL}</strong></div>
          <span className="read-only-label">READ ONLY</span>
        </div>
        <p className="setting-note">Set <code>VITE_API_BASE_URL</code> in the frontend environment file to change this address. Alert thresholds are saved separately in the backend settings above.</p>
      </Panel>
    </div>
  );
}
