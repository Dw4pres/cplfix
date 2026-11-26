# CPLfix KiCad Plugin

Normalize your board's placement rotations for JLCPCB, PCBWay or
MacroFab — from inside KiCad's PCB editor. No accounts, no API key, no
payment: the plugin sends your placement to the free CPLfix API
(https://cplfix.com) and saves the corrected CPL next to your board
file as `cpl-<cm>.csv`.

All rotation math lives in the API (spec v1.1 §4.3). The plugin only
builds the `.pos` text and reports what the API returns.

## Install

### Once published (Plugin and Content Manager)
1. KiCad → Plugin and Content Manager → search **CPLfix** → Install.
2. Restart the PCB editor. The plugin appears under
   **Tools → External Plugins → CPLfix — Normalize CPL Rotations**.

### Manual install (works today)
1. Download the latest release zip (`cplfix-1.0.0.zip`) — or build it
   with `python3 build_zip.py` (needs `jsonschema` + `Pillow`, stdlib
   otherwise).
2. Unzip it. Copy the contents of `plugins/` into your KiCad plugins
   folder:
   - Windows: `%APPDATA%\kicad\<version>\plugins\`
   - macOS: `~/Library/Application Support/kicad/<version>/plugins/`
   - Linux: `~/.local/share/kicad/<version>/plugins/`
3. Restart the PCB editor.

## Use
1. Open your board (`.kicad_pcb`).
2. Tools → External Plugins → **CPLfix — Normalize CPL Rotations**.
3. Pick the target CM (default JLCPCB) and, only if your `.pos` export
   used it, tick "Input used KiCad 'negative X on bottom' export".
4. The plugin saves `cpl-<cm>.csv` next to the board file, plus
   `<board>.cplfix.pos` (the exact placement text it sent, so you can
   reproduce a result by hand), and shows a short report: parts
   normalized, how many rotations changed, warnings.

Always verify every part in your CM's placement preview before
ordering — it is the final authority.

## How it works
- Reads footprints with the pcbnew API (`GetFootprints`,
  `GetPosition`, `GetOrientationDegrees`, `GetFPID`, `GetLayer`),
  positions relative to the board's aux origin — the same reference
  KiCad's own `.pos` export uses.
- Builds a KiCad ASCII `.pos` text (spec v1.1 §4.1) and POSTs it to
  `POST https://cplfix.com/api/v1/normalize/:cm`.
- The API returns the corrected CSV plus `matchedRules` and `warnings`,
  which the plugin summarises. Warnings never block the save; they are
  shown in the report.

## Compatibility
- KiCad **7, 8 and 9** (SWIG `pcbnew` runtime — see `metadata.json`,
  `runtime: swig`, `kicad_version_max: 9.0`).
- KiCad 9 deprecated the SWIG bindings and KiCad 10 removes them; an
  IPC-API version of this plugin will be needed for KiCad 10+.
- Needs network access to `cplfix.com`. If the API cannot be reached,
  the plugin reports the failure in a message box — never a traceback.

## Files
| File | What it is |
| --- | --- |
| `plugins/cplfix.py` | The ActionPlugin wrapper (dialog, file saving, report). |
| `plugins/cplfix_core.py` | Pure logic: `.pos` building, board reading, API client. No `pcbnew` import — testable in plain Python. |
| `plugins/__init__.py` | Empty package marker. |
| `metadata.json` | PCM v1 package metadata (archive copy — no `download_*` keys, per the KiCad docs). |
| `metadata.submit.json` | Submission copy with `download_*` placeholders — fill in at publish time. |
| `resources/icon.png` | 64×64 PCM icon. |
| `schemas/pcm.v1.schema.json` | Vendored KiCad PCM v1 schema (from https://go.kicad.org/pcm/schemas/v1). |
| `build_zip.py` | Validates `metadata.json` and builds `dist/cplfix-1.0.0.zip`. |
| `tests/test_plugin.py` | Unit tests with a stubbed pcbnew, incl. a live API check. |

## Tests
```
python3 -m unittest discover -s tests -v
```
5 tests: `.pos` building against the sample board, no-pcbnew import,
bad-CM / empty-input rejection, and a live POST to the production API
verifying the hand-checked rows (`U1,10,-20,Top,270`,
`U2,30,-20,Bottom,0`, `Q1,40,-10,Bottom,90`).

## Publishing (not done — needs Casey's steps)
1. Create the public GitHub repo and a `v1.0.0` release with
   `dist/cplfix-1.0.0.zip` attached.
2. Copy the zip's SHA-256, byte size and install size (printed by
   `build_zip.py`) into `metadata.submit.json`, replacing the
   `download_*` placeholders.
3. Submit `metadata.submit.json` to the KiCad addons repository
   (https://gitlab.com/kicad/addons/metadata) — the KiCad team reviews
   it; the package must be open-source (MIT here) and the identifier
   `com.cplfix.cplfix` must be unique.

Docs used: https://dev-docs.kicad.org/en/addons/ (PCM packaging +
metadata), https://go.kicad.org/pcm/schemas/v1 (v1 schema),
https://docs.kicad.org/doxygen-python-6.0/classpcbnew_1_1FOOTPRINT.html
(FOOTPRINT API).
