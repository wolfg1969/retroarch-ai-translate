import { callable } from "@decky/api";
import {
  staticClasses,
  ButtonItem,
  SteamSpinner,
} from "@decky/ui";
import { usePolling } from "../hooks/usePolling";

interface StatusResponse {
  running: boolean;
  port: number;
  host: string;
  vision_model: string;
  translate_model: string;
  has_vision_key: boolean;
  has_translate_key: boolean;
  cjk_font_path: string;
}

const getStatus = callable<[], StatusResponse>("get_status");
const startService = callable<[], StatusResponse>("start_service");
const stopService = callable<[], StatusResponse>("stop_service");

export default function StatusPanel() {
  const { data: status, error, loading } = usePolling(
    () => getStatus(),
    3000
  );

  const handleToggle = async () => {
    if (status?.running) {
      await stopService();
    } else {
      await startService();
    }
  };

  const dotColor = status?.running ? "#4caf50" : "#f44336";
  const statusText = status?.running ? "Running" : "Stopped";

  return (
    <div>
      <div className={staticClasses.PanelSectionTitle}>
        Service Status
      </div>

      <div className={staticClasses.PanelSection}>
        {loading && !status ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              padding: "12px",
              gap: "8px",
            }}
          >
            <SteamSpinner /> <span>Loading…</span>
          </div>
        ) : (
          <>
            {/* Status indicator */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                padding: "10px 16px",
                gap: "10px",
                borderBottom: "1px solid rgba(255,255,255,0.05)",
              }}
            >
              <span
                style={{
                  width: "12px",
                  height: "12px",
                  borderRadius: "50%",
                  backgroundColor: dotColor,
                  display: "inline-block",
                  flexShrink: 0,
                }}
              />
              <span style={{ fontWeight: 600 }}>{statusText}</span>
              {status?.running && (
                <span style={{ color: "#888", fontSize: "0.85em" }}>
                  {status.host}:{status.port}
                </span>
              )}
            </div>

            {/* Model info */}
            {status && (
              <div
                style={{
                  padding: "8px 16px",
                  fontSize: "0.82em",
                  color: "#aaa",
                }}
              >
                <div>OCR: {status.vision_model}</div>
                <div>MT: {status.translate_model}</div>
                <div>
                  API Keys:{" "}
                  <span style={{ color: status.has_vision_key ? "#4caf50" : "#f44336" }}>
                    Vision {status.has_vision_key ? "✓" : "✗"}
                  </span>
                  {" · "}
                  <span style={{ color: status.has_translate_key ? "#4caf50" : "#aaa" }}>
                    MT {status.has_translate_key ? "✓" : "(free)"}
                  </span>
                </div>
              </div>
            )}

            {error && (
              <div style={{ padding: "8px 16px", color: "#f44336", fontSize: "0.82em" }}>
                Error: {error}
              </div>
            )}

            {/* Start / Stop button */}
            <ButtonItem
              onClick={handleToggle}
              disabled={loading}
            >
              {status?.running ? "⏹ Stop Service" : "▶ Start Service"}
            </ButtonItem>
          </>
        )}
      </div>
    </div>
  );
}
