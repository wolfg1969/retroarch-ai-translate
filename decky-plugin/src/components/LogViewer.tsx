import { useState, useRef, useEffect } from "react";
import { callable } from "@decky/api";
import { PanelSection, PanelSectionRow, ButtonItem } from "@decky/ui";
import { usePolling } from "../hooks/usePolling";

const getLogs = callable<[number], string[]>("get_logs");

export default function LogViewer() {
  const [expanded, setExpanded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const { data: logs } = usePolling(
    () => getLogs(50),
    expanded ? 2000 : 30000
  );

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 30);
  };

  return (
    <PanelSection title="Logs">
      <PanelSectionRow>
        <ButtonItem onClick={() => setExpanded(!expanded)}>
          {expanded ? "▼ Hide" : "▶ Show"} Logs
          {logs && logs.length > 0 && (
            <span style={{ color: "#888", marginLeft: "8px" }}>
              ({logs.length} lines)
            </span>
          )}
        </ButtonItem>
      </PanelSectionRow>

      {expanded && (
        <PanelSectionRow>
          <div>
            <div
              ref={scrollRef}
              onScroll={handleScroll}
              style={{
                height: "180px",
                overflowY: "auto",
                backgroundColor: "rgba(0,0,0,0.4)",
                padding: "8px",
                fontFamily: "monospace",
                fontSize: "11px",
                lineHeight: "1.4",
                color: "#ccc",
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
                borderRadius: "4px",
              }}
            >
              {logs && logs.length > 0 ? (
                logs.map((line, i) => <div key={i}>{line}</div>)
              ) : (
                <div style={{ color: "#666" }}>No logs yet…</div>
              )}
            </div>
            {!autoScroll && (
              <div
                style={{
                  textAlign: "center",
                  padding: "4px",
                  fontSize: "10px",
                  color: "#888",
                }}
              >
                Auto-scroll paused (scroll down to resume)
              </div>
            )}
            <div style={{ marginTop: "4px", fontSize: "10px", color: "#666", textAlign: "center" }}>
              完整历史、筛选与下载：<a style={{ color: "#888" }} href="/settings" target="_blank" rel="noopener noreferrer">浏览器 Web Settings</a>
            </div>
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
