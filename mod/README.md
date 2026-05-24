# Vox Dynastica — CK3 Mod (Phase 1 v0.1.0)

The in-game half of the Vox Dynastica project. Adds a **Royal Library** tab to
the Royal Court window, mounted alongside the vanilla *Throne Room / Court
Artifacts / Court Grandeur / Court Visuals* tabs.

> **Status:** Phase 1 first cut — GUI + sample entries are in place.
> **Phase 1.1** added the `chronicler emit-loc` writer (LLM → loc YAML), so
> the library can now be rebuilt from the DB on demand. The save-watching
> companion (`vox-companion`) that automates that call after each autosave
> is the remaining Phase 1.1 work.

## What's in the box

```
mod/
├── vox_dynastica.mod          # user-side descriptor (copied to Paradox/CK3/mod/)
└── vox-dynastica/
    ├── descriptor.mod         # in-mod descriptor
    ├── gui/
    │   ├── window_royal_court.gui     # vanilla file + Royal Library button
    │   └── window_royal_library.gui   # the parchment overlay
    ├── gfx/interface/icons/vox_dynastica/
    │   └── roco_library.dds   # placeholder — currently a copy of roco_grandeur
    └── localization/
        ├── english/vox_dynastica_l_english.yml
        └── simp_chinese/vox_dynastica_l_simp_chinese.yml
```

## How the GUI hook works

CK3's tab system (`RoyalCourtWindow.SetActiveTab('throne'|'artifacts'|...)`) is
a **hardcoded C++ enum** — we cannot register a 5th value. So the Royal Library
button looks like a vanilla tab but does not participate in the active-tab
machinery. Instead it toggles a `VariableSystem` key:

- The button calls `[GetVariableSystem.Toggle('vd_royal_library_open')]`
- A `vd_royal_library_window` overlay (sibling of `widget_royal_court_screenshot_window`)
  watches that key and renders a parchment list on top of the court scene
- Closing the window or clicking the tab again clears the key

This piggybacks on the same pattern vanilla uses for screenshot mode and
artifact placement, so visually and behaviourally it matches.

## Install (local dev)

The user-side `.mod` descriptor at
`Documents/Paradox Interactive/Crusader Kings III/mod/vox_dynastica.mod`
points to this repo path. Enable in the CK3 launcher's playset.

After any GUI edit, in-game console: `reload gui`. After any loc edit:
`reload localization` (debug-mode + non-ironman only).

## Known limitations (Phase 1 first cut)

1. **Entry list is statically defined** — 30 hardcoded slots backed by loc keys
   `vd_entry_01..30`. No data-model binding. Empty slots render as blank rows
   (small visual gap).
2. **Tab icon is a placeholder** (`roco_library.dds` = copy of `roco_grandeur.dds`).
   Custom art TODO before any public release.
3. **Companion is half-done** — the `chronicler emit-loc` subcommand
   landed in Phase 1.1 (LLM → loc YAML, reverse-chrono, UTF-8 BOM, colour
   tags wired). The save-watcher tray app that calls it after each
   autosave is still pending.
4. **GUI conflicts** — because we ship a full copy of `window_royal_court.gui`,
   we conflict with any other mod that patches the same file. Standard CK3
   GUI-mod tradeoff; document in user-facing README before Workshop release.

## Regenerating the library from the DB (Phase 1.1)

After you've run `chronicler generate` (or `chronicler watch --generate`)
to build chronicles into a SQLite DB, push them into the in-game library:

```bash
chronicler emit-loc \
    --db campaign.db \
    --mod-dir mod/vox-dynastica \
    --lang all
```

This rewrites `localization/english/vox_dynastica_l_english.yml` and
`localization/simp_chinese/vox_dynastica_l_simp_chinese.yml` with the
newest 30 `court_historian` entries per language, in reverse chronological
order (slot 01 = newest), UTF-8 BOM included. In-game, run
`reload localization` (debug + non-ironman) to pick up the change without
restarting CK3.

## Next up

- `vox-companion` tray app — watches `Documents/.../save games/` for autosaves,
  runs the pipeline, calls `emit-loc`, posts a tray notification (Tier 2 behaviour;
  Tier 1 keypress injection deferred to Phase 1.5)
- Empty-slot hiding via `on_game_start` reading `vd_entry_count` (Phase 1.2)
- Custom tab icon (DDS, BC3, mip-mapped) once art lands
