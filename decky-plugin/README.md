# RetroArch AI Translation — Decky Plugin

Real-time Japanese→Chinese translation overlay for RetroArch games, managed
from the Steam Deck Quick Access Menu.

## Features

- **Start/Stop** the translation HTTP server from QAM
- **Switch game configs** (Phoenix Wright, Fire Emblem, Zelda, etc.)
- **Configure API keys** for Vision OCR and Machine Translation
- **View live logs** from the translation pipeline
- **Auto-start** on plugin load (configurable)

## Requirements

- Steam Deck with [Decky Loader](https://decky.xyz) installed
- RetroArch installed (Flatpak or native)
- A Vision API key (e.g., [SiliconFlow](https://siliconflow.cn))
- Optional: a Translate API key (falls back to free MT model)

## Installation

### From the Decky Plugin Store (coming soon)

1. Open Decky → Store → search "RetroArch AI Translation" → Install

### Manual Install

1. Download the latest `retroarch-ai-translation.zip` from Releases
2. Extract to `~/homebrew/plugins/retroarch-ai-translation/`
3. Restart Decky: `systemctl restart plugin_loader.service`
4. The plugin appears in QAM under "AI Translation"

### CJK Font

The plugin needs a CJK font for rendering Chinese text overlays. Options:

- **Recommended (Steam Deck)**: Install the system package:
  ```bash
  sudo pacman -S wqy-zenhei
  ```
- **Bundled**: Run `./download-font.sh` before packaging to bundle the font
- **Custom**: Set any CJK `.ttc` path in plugin settings

## RetroArch Configuration

1. **Settings → AI 服务 → AI 服务开关** = ON
2. **Settings → AI 服务 → AI 服务模式** = **Image (mode 0)**
3. **Settings → AI 服务 → AI 服务网址** = `http://127.0.0.1:4404`
4. **Settings → AI 服务 → 翻译时暂停** = ON
5. **Settings → 输入 → 快捷键 → AI 服务** — bind a button

## Usage

1. Open QAM (••• button) → AI Translation
2. If needed, configure API keys in "API Settings"
3. Press **Start Service**
4. Launch a Japanese game in RetroArch
5. Press your AI Service hotkey → Chinese text overlay appears!

## Game Configs

Built-in support for:
- **逆转裁判** (Phoenix Wright: Ace Attorney, `gyakuten`)
- **火焰纹章** (Fire Emblem, `fire_emblem`)
- **塞尔达传说 缩小帽** (Zelda: Minish Cap, `zelda_minish`)

Switch games from the QAM dropdown. Configs are loaded from
`~/homebrew/settings/retroarch-ai-translation/game_config.yaml`.

To add custom games, edit that file with additional YAML documents.
See the [main project docs](../templates/game_config.yaml) for the config format.

## Development

```bash
# Frontend
cd decky-plugin
pnpm install
pnpm run build      # or pnpm run watch

# Python backend (test locally)
python3 main.py

# Package for distribution
pnpm run package
```

### Directory Structure

```
decky-plugin/
├── main.py              # Python backend (Plugin class)
├── src/                 # React frontend (TypeScript)
│   ├── index.tsx        # Entry point
│   └── components/      # UI components
├── py_modules/          # Vendored Python modules
│   └── retroarch_ai/    # Translation service core
├── defaults/            # Default game configs
├── assets/              # Icons + bundled font
├── plugin.json          # Decky metadata
└── package.json         # Frontend deps
```

## License

MIT — see [../LICENSE](../LICENSE)
