import { useState, useEffect } from "react";
import { callable, toaster } from "@decky/api";
import {
  staticClasses,
  TextField,
  ButtonItem,
  ToggleField,
} from "@decky/ui";

interface SettingsResponse {
  vision_api_key: string;
  translate_api_key: string;
  translate_base_url: string;
  translate_model: string;
  listen_port: number;
  auto_start: boolean;
  cjk_font_path: string;
}

const getSettings = callable<[], SettingsResponse>("get_settings");
const saveSettingsRPC = callable<
  [Partial<SettingsResponse>],
  { success: boolean; error?: string }
>("save_settings");

export default function ApiKeySettings() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);

  // Local form state
  const [visionKey, setVisionKey] = useState("");
  const [translateKey, setTranslateKey] = useState("");
  const [translateUrl, setTranslateUrl] = useState("");
  const [translateModel, setTranslateModel] = useState("");
  const [port, setPort] = useState("4404");
  const [autoStart, setAutoStart] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const s = await getSettings();
        setSettings(s);
        // Only pre-fill fields if the user hasn't typed anything
        if (!visionKey) setVisionKey(s.vision_api_key);
        if (!translateKey) setTranslateKey(s.translate_api_key);
        if (!translateUrl) setTranslateUrl(s.translate_base_url);
        if (!translateModel) setTranslateModel(s.translate_model);
        if (port === "4404") setPort(String(s.listen_port));
        setAutoStart(s.auto_start);
      } catch (e) {
        console.error("Failed to load settings:", e);
      }
    })();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      const result = await saveSettingsRPC({
        vision_api_key: visionKey,
        translate_api_key: translateKey,
        translate_base_url: translateUrl,
        translate_model: translateModel,
        listen_port: parseInt(port, 10) || 4404,
        auto_start: autoStart,
      });
      if (result.success) {
        toaster.toast({
          title: "Settings Saved",
          body: "API keys and configuration updated.",
        });
      } else {
        toaster.toast({
          title: "Error",
          body: result.error || "Failed to save settings",
        });
      }
    } catch (e) {
      toaster.toast({ title: "Error", body: String(e) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className={staticClasses.PanelSectionTitle}>
        API Settings
      </div>

      <div className={staticClasses.PanelSection}>
        <ButtonItem onClick={() => setExpanded(!expanded)}>
          {expanded ? "▼ Hide" : "▶ Configure"} API Keys & Model
        </ButtonItem>

        {expanded && (
          <div>
            {/* Vision API Key */}
            <div
              style={{
                padding: "10px 16px 4px",
                borderTop: "1px solid rgba(255,255,255,0.05)",
              }}
            >
              <TextField
                label="Vision API Key"
                description="SiliconFlow or compatible API key for OCR"
                value={visionKey}
                onChange={(e) => setVisionKey((e.target as HTMLInputElement).value)}
                bIsPassword
              />
            </div>

            {/* Translate API Key */}
            <div style={{ padding: "4px 16px" }}>
              <TextField
                label="Translate API Key"
                description="Optional: leave empty for free MT model"
                value={translateKey}
                onChange={(e) =>
                  setTranslateKey((e.target as HTMLInputElement).value)
                }
                bIsPassword
              />
            </div>

            {/* Translate Base URL */}
            <div style={{ padding: "4px 16px" }}>
              <TextField
                label="Translate API URL"
                description="OpenAI-compatible chat completions endpoint"
                value={translateUrl}
                onChange={(e) =>
                  setTranslateUrl((e.target as HTMLInputElement).value)
                }
              />
            </div>

            {/* Translate Model */}
            <div style={{ padding: "4px 16px" }}>
              <TextField
                label="Translate Model"
                description="Model name for translation"
                value={translateModel}
                onChange={(e) =>
                  setTranslateModel((e.target as HTMLInputElement).value)
                }
              />
            </div>

            {/* Port */}
            <div style={{ padding: "4px 16px" }}>
              <TextField
                label="Listen Port"
                description="HTTP server port (requires restart)"
                value={port}
                onChange={(e) =>
                  setPort((e.target as HTMLInputElement).value)
                }
                mustBeNumeric
              />
            </div>

            {/* Auto-start */}
            <div
              style={{
                padding: "8px 16px",
                borderBottom: "1px solid rgba(255,255,255,0.05)",
              }}
            >
              <ToggleField
                label="Auto-start on plugin load"
                checked={autoStart}
                onChange={(checked: boolean) => setAutoStart(checked)}
              />
            </div>

            {/* Save button */}
            <ButtonItem onClick={handleSave} disabled={saving}>
              {saving ? "Saving…" : "💾 Save Settings"}
            </ButtonItem>
          </div>
        )}
      </div>
    </div>
  );
}
