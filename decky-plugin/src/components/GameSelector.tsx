import { useState, useEffect } from "react";
import { callable, toaster } from "@decky/api";
import { staticClasses, Dropdown, ButtonItem } from "@decky/ui";

interface GameInfo {
  id: string;
  name: string;
}

interface StatusResponse {
  running: boolean;
}

const getGames = callable<[], GameInfo[]>("get_games");
const getStatus = callable<[], StatusResponse>("get_status");
const saveSettings = callable<[{ game_id: string }], { success: boolean }>(
  "save_settings"
);

export default function GameSelector() {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const list = await getGames();
        setGames(list);
      } catch (e) {
        console.error("Failed to load games:", e);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const dropdownOptions = [
    { data: "", label: "Auto-detect" },
    ...games.map((g) => ({ data: g.id, label: `${g.name} (${g.id})` })),
  ];

  const handleChange = async (option: { data: string }) => {
    setSelected(option.data);
    try {
      await saveSettings({ game_id: option.data });
      toaster.toast({
        title: "Game Switched",
        body: option.data
          ? `Active game: ${option.data}`
          : "Auto-detect mode",
      });
    } catch (e) {
      toaster.toast({
        title: "Error",
        body: String(e),
      });
    }
  };

  return (
    <div>
      <div className={staticClasses.PanelSectionTitle}>
        Game Configuration
      </div>

      <div className={staticClasses.PanelSection}>
        <div
          style={{
            padding: "10px 16px",
            borderBottom: "1px solid rgba(255,255,255,0.05)",
          }}
        >
          <Dropdown
            rgOptions={dropdownOptions}
            selectedOption={selected}
            onChange={handleChange}
            strDefaultLabel={
              loading ? "Loading games…" : "Select a game"
            }
            menuLabel="Games"
          />
        </div>
      </div>
    </div>
  );
}
