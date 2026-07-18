import { PanelSection, PanelSectionRow } from "@decky/ui";
import { usePolling } from "../hooks/usePolling";
import { callable } from "@decky/api";

interface StatusResponse {
  running: boolean;
  port: number;
}

const getStatus = callable<[], StatusResponse>("get_status");

export default function ApiKeySettings() {
  const { data: status } = usePolling(() => getStatus(), 5000);
  const port = status?.port || 4404;

  return (
    <PanelSection title="API Settings">
      <PanelSectionRow>
        <div
          style={{
            padding: "8px 0",
            fontSize: "0.85em",
            color: "#aaa",
            lineHeight: 1.6,
          }}
        >
          <p>在手机或电脑浏览器打开：</p>
          <p style={{ color: "#4caf50" }}>
            http://&lt;Steam Deck IP&gt;:{port}/settings
          </p>
          <p style={{ fontSize: "0.9em", marginTop: "0.5em" }}>
            {status?.running
              ? "翻译服务已运行，在浏览器中粘贴 API Key 即可。"
              : "请先启动翻译服务。"}
          </p>
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}
