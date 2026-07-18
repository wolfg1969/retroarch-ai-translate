import { useState } from "react";
import { callable } from "@decky/api";
import {
  PanelSection,
  PanelSectionRow,
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

  const [actionError, setActionError] = useState<string | null>(null);

  const handleToggle = async () => {
    setActionError(null);
    try {
      if (status?.running) {
        await stopService();
      } else {
        const result = await startService();
        if ((result as any).error) {
          setActionError((result as any).error);
        }
      }
    } catch (e) {
      setActionError(String(e));
    }
  };

  const dotColor = status?.running ? "#4caf50" : "#f44336";
  const statusText = status?.running ? "Running" : "Stopped";

  return (
    <PanelSection title="Service Status">
      {loading && !status ? (
        <PanelSectionRow>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "4px 0",
            }}
          >
            <SteamSpinner /> <span>Loading…</span>
          </div>
        </PanelSectionRow>
      ) : (
        <>
          {/* Status indicator */}
          <PanelSectionRow>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "10px",
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
          </PanelSectionRow>

          {/* Model info */}
          {status && (
            <PanelSectionRow>
              <div style={{ fontSize: "0.82em", color: "#aaa" }}>
                <div>OCR: {status.vision_model}</div>
                <div>MT: {status.translate_model}</div>
                <div>
                  API Keys:{" "}
                  <span
                    style={{
                      color: status.has_vision_key ? "#4caf50" : "#f44336",
                    }}
                  >
                    Vision {status.has_vision_key ? "✓" : "✗"}
                  </span>
                  {" · "}
                  <span
                    style={{
                      color: status.has_translate_key ? "#4caf50" : "#aaa",
                    }}
                  >
                    MT {status.has_translate_key ? "✓" : "(free)"}
                  </span>
                </div>
              </div>
            </PanelSectionRow>
          )}

          {(error || actionError) && (
            <PanelSectionRow>
              <div style={{ color: "#f44336", fontSize: "0.82em" }}>
                {actionError || error}
              </div>
            </PanelSectionRow>
          )}

          {/* Start / Stop button */}
          <PanelSectionRow>
            <ButtonItem onClick={handleToggle} disabled={loading}>
              {status?.running ? "⏹ Stop Service" : "▶ Start Service"}
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
}
