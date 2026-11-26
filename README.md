# CPLfix

Fix your KiCad rotations before JLCPCB solders them wrong.

CPLfix corrects pick-and-place (CPL) placement rotations for JLCPCB,
PCBWay and MacroFab. The web tool is at [cplfix.com](https://cplfix.com)
— free, no accounts, no API key. This repo holds the integrations that
call the same API, so the numbers can never disagree with the site:

- **[kicad-plugin/](kicad-plugin/)** — KiCad ActionPlugin (KiCad 7/8/9).
  Runs from the PCB editor, sends the open board's placement to the
  CPLfix API, saves the corrected CSV next to the board. See its
  README for install steps; the `v1.0.0` release zip is what gets
  submitted to the KiCad Plugin and Content Manager.
- **[github-action/](github-action/)** — `normalize-cpl-action`. Finds
  `.pos`/`.csv` files in a repo, normalizes each via the API on every
  push, writes the corrected CSVs. See its README for the workflow
  snippet.

All rotation math lives in the API. Neither integration reimplements it:
the plugin only builds the `.pos` text and the action only posts files
and writes back what the API returns. The reference for the math is
the JLCPCB bottom rule `(180 − rot + delta) % 360` — PCBWay and
MacroFab apply no delta by design.

## Links

- Web tool + rotation reference pages: https://cplfix.com
- Integrations: https://cplfix.com/integrations/
- API: `POST https://cplfix.com/api/v1/normalize/:cm`
