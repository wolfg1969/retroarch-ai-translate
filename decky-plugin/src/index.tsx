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
    name: "AI Translation",
    titleView: <div className={staticClasses.Title}>AI Translation</div>,
    content: <MainPanel />,
    icon: <FaLanguage />,
    onDismount() {},
  };
});
