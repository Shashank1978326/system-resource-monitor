import { useEffect, useState } from "react";
import {
  errorMessage,
  getNetworkInterfaces,
  getNetworkInterfaceTraffic,
} from "../../services/api";
import { formatBytes, formatRate } from "../../utils/format";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import Panel from "../common/Panel";

const METADATA_REFRESH_INTERVAL_MS = 30_000;
const TRAFFIC_REFRESH_INTERVAL_MS = 1_000;

function display(value, suffix = "") {
  return value == null || value === "" ? "Unavailable" : `${value}${suffix}`;
}

export default function NetworkInterfaceList() {
  const [interfaces, setInterfaces] = useState(null);
  const [traffic, setTraffic] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [trafficError, setTrafficError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let mounted = true;
    let controller;

    const refresh = async () => {
      controller?.abort();
      controller = new AbortController();
      try {
        const response = await getNetworkInterfaces({
          signal: controller.signal,
        });
        if (mounted) {
          setInterfaces(response.interfaces);
          setError(null);
        }
      } catch (requestError) {
        if (mounted && !controller.signal.aborted) {
          setError(errorMessage(requestError));
        }
      } finally {
        if (mounted) setLoading(false);
      }
    };

    refresh();
    const intervalId = window.setInterval(
      refresh,
      METADATA_REFRESH_INTERVAL_MS,
    );
    return () => {
      mounted = false;
      window.clearInterval(intervalId);
      controller?.abort();
    };
  }, [reloadKey]);

  useEffect(() => {
    let mounted = true;
    let controller;
    let timerId;

    const refresh = async () => {
      controller = new AbortController();
      try {
        const response = await getNetworkInterfaceTraffic({
          signal: controller.signal,
        });
        if (mounted) {
          setTraffic(response);
          setTrafficError(null);
        }
      } catch (requestError) {
        if (mounted && !controller.signal.aborted) {
          setTrafficError(errorMessage(requestError));
        }
      } finally {
        if (mounted) {
          timerId = window.setTimeout(refresh, TRAFFIC_REFRESH_INTERVAL_MS);
        }
      }
    };

    refresh();
    return () => {
      mounted = false;
      window.clearTimeout(timerId);
      controller?.abort();
    };
  }, []);

  const trafficByName = new Map(
    (traffic?.interfaces || []).map((item) => [item.name, item]),
  );
  const maxDownload = Math.max(
    0,
    ...(traffic?.interfaces || []).map(
      (item) => item.download_speed_bytes_per_sec || 0,
    ),
  );
  const maxUpload = Math.max(
    0,
    ...(traffic?.interfaces || []).map(
      (item) => item.upload_speed_bytes_per_sec || 0,
    ),
  );

  return (
    <Panel
      title="Network interfaces"
      subtitle="Interface details refresh every 30 seconds · traffic refreshes every second"
      className="network-interface-panel"
    >
      <ErrorBanner
        message={error}
        onRetry={() => {
          setLoading(interfaces === null);
          setReloadKey((key) => key + 1);
        }}
      />
      <ErrorBanner message={trafficError} />
      {loading && interfaces === null && (
        <Skeleton className="network-interface-skeleton" />
      )}
      {!loading && !error && interfaces?.length === 0 && (
        <EmptyState
          title="No network interfaces found"
          message="The operating system did not report any available interfaces."
        />
      )}
      {interfaces?.length > 0 && (
        <div className="network-interface-grid">
          {interfaces.map((item) => {
            const counters = trafficByName.get(item.name);
            const status =
              item.is_up === true
                ? "active"
                : item.is_up === false
                  ? "inactive"
                  : "unknown";
            return (
              <article className="network-interface-card" key={item.name}>
                <div className="network-interface-heading">
                  <strong title={item.name}>{item.name}</strong>
                  <span className={`interface-status interface-status-${status}`}>
                    {status === "active"
                      ? "Active"
                      : status === "inactive"
                        ? "Inactive"
                        : "Status unavailable"}
                  </span>
                </div>
                <dl className="network-interface-properties">
                  <div>
                    <dt>IPv4</dt>
                    <dd>{display(item.ipv4_address)}</dd>
                  </div>
                  <div>
                    <dt>IPv6</dt>
                    <dd>{display(item.ipv6_address)}</dd>
                  </div>
                  <div>
                    <dt>Link speed</dt>
                    <dd>{display(item.speed_mbps, " Mbps")}</dd>
                  </div>
                  <div>
                    <dt>MTU</dt>
                    <dd>{display(item.mtu)}</dd>
                  </div>
                </dl>
                <div className="network-interface-traffic">
                  <div className="interface-traffic-row">
                    <span>Download</span>
                    <strong>
                      {counters?.download_status === "available"
                        ? formatRate(counters.download_speed_bytes_per_sec)
                        : counters?.download_status === "initializing"
                          ? "Waiting for sample"
                          : "Unavailable"}
                    </strong>
                  </div>
                  <div
                    className="interface-traffic-track"
                    role="progressbar"
                    aria-label={`${item.name} download activity`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={
                      maxDownload > 0 &&
                      counters?.download_speed_bytes_per_sec != null
                        ? Math.round(
                            (counters.download_speed_bytes_per_sec /
                              maxDownload) *
                              100,
                          )
                        : 0
                    }
                  >
                    <span
                      className="interface-download-bar"
                      style={{
                        width:
                          maxDownload > 0 &&
                          counters?.download_speed_bytes_per_sec != null
                            ? `${(counters.download_speed_bytes_per_sec / maxDownload) * 100}%`
                            : "0%",
                      }}
                    />
                  </div>
                  <div className="interface-traffic-row">
                    <span>Upload</span>
                    <strong>
                      {counters?.upload_status === "available"
                        ? formatRate(counters.upload_speed_bytes_per_sec)
                        : counters?.upload_status === "initializing"
                          ? "Waiting for sample"
                          : "Unavailable"}
                    </strong>
                  </div>
                  <div
                    className="interface-traffic-track"
                    role="progressbar"
                    aria-label={`${item.name} upload activity`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={
                      maxUpload > 0 &&
                      counters?.upload_speed_bytes_per_sec != null
                        ? Math.round(
                            (counters.upload_speed_bytes_per_sec / maxUpload) *
                              100,
                          )
                        : 0
                    }
                  >
                    <span
                      className="interface-upload-bar"
                      style={{
                        width:
                          maxUpload > 0 &&
                          counters?.upload_speed_bytes_per_sec != null
                            ? `${(counters.upload_speed_bytes_per_sec / maxUpload) * 100}%`
                            : "0%",
                      }}
                    />
                  </div>
                  <div className="interface-traffic-totals">
                    <span>
                      Received <strong>{formatBytes(counters?.bytes_received)}</strong>
                    </span>
                    <span>
                      Sent <strong>{formatBytes(counters?.bytes_sent)}</strong>
                    </span>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
