import { definePlugin } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { FaLanguage } from "react-icons/fa";
import StatusPanel from "./components/StatusPanel";
import GameSelector from "./components/GameSelector";
import ApiKeySettings from "./components/ApiKeySettings";
import LogViewer from "./components/LogViewer";

const MainPanel = () => {
  return (
    <div>
      <StatusPanel />
      <GameSelector />
      <ApiKeySettings />
      <LogViewer />
    </div>
  );
};

export default definePlugin(() => {
  return {
    name: "RetroArch AI Translate",
    titleView: <div className={staticClasses.Title}>RetroArch AI Translate</div>,
    content: <MainPanel />,
    icon: <FaLanguage />,
    onDismount() {},
  };
});
