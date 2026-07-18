import { useState, useEffect } from "react";
import { callable, toaster } from "@decky/api";
import { PanelSection, PanelSectionRow, Dropdown } from "@decky/ui";

interface GameInfo {
  id: string;
  name: string;
}

const getGames = callable<[], GameInfo[]>("get_games");
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
    <PanelSection title="Game Configuration">
      <PanelSectionRow>
        <Dropdown
          rgOptions={dropdownOptions}
          selectedOption={selected}
          onChange={handleChange}
          strDefaultLabel={
            loading ? "Loading games…" : "Select a game"
          }
          menuLabel="Games"
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
