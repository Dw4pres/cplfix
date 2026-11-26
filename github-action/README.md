# CPLfix GitHub Action — `normalize-cpl-action`

Normalize pick-and-place (CPL) rotations for JLCPCB, PCBWay or
MacroFab on every push, via the free CPLfix API. No accounts, no API
key, no secrets, no payment.

All rotation math lives in the API (spec v1.1 §4.3). This action only
moves files and reports what the API returns.

## Use it in your hardware repo

```yaml
- name: Normalize CPL for JLCPCB
  id: cplfix
  uses: Dw4pres/cplfix/github-action@v1
  with:
    cm: jlcpcb            # jlcpcb | pcbway | macrofab
    files: '**/*.pos'     # glob of .pos/.csv placement files
```

The normalized CSV is written next to each source file with the
suffix `.normalized.csv` (e.g. `board.pos` →
`board.normalized.csv`) — upload that file to your fab. Warnings never
fail the run; the run fails only on API errors or unparseable files.

## Inputs / outputs

| Input | Default | Meaning |
| --- | --- | --- |
| `cm` | `jlcpcb` | Target CM: `jlcpcb`, `pcbway` or `macrofab` |
| `files` | `**/*.pos` | Glob (one per line) of `.pos`/`.csv` files |
| `api-base` | `https://cplfix.com` | CPLfix API base URL |
| `output-suffix` | `.normalized.csv` | Suffix for the normalized file |

| Output | Meaning |
| --- | --- |
| `files-normalized` | Number of placement files normalized |
| `parts-changed` | Total parts whose rotation changed |
| `warnings` | Total warnings reported by the API |

A step summary with the per-file results is written to the run's
summary page.

## Why Python, not shell/curl
The runner is a single Python 3 stdlib script (`scripts/normalize.py`,
urllib only). Python 3 ships on every GitHub-hosted runner
(ubuntu/windows/macos), so there is no npm install step and no
curl/jq quoting or glob behaviour that differs per shell and OS.

## Failure behaviour
- **Warnings never fail the run.** A part with no matching rule, or a
  MacroFab rotation-sign warning, is counted and printed — the
  normalized file is still written.
- **The run fails** on API errors (non-200, unreachable API) and on
  unparseable files (empty file, no files matched). A failed file aborts
  the run so a bad placement file can never silently ship.

## Test locally
```
# From app/ (uses the repo's own sample board):
python3 github-action/scripts/normalize.py --cm jlcpcb \
  --files 'samples/sample.pos' --output-suffix '.normalized.csv'
# Check the hand-checked rows in samples/sample.normalized.csv:
#   U1,10,-20,Top,270 / U2,30,-20,Bottom,0 / Q1,40,-10,Bottom,90
```
An example CI workflow is in `.github/workflows/test-normalize.yml`
— copy it into your repo's `.github/workflows/` (replacing `uses: ./`
with the published action).

## Publishing (not done — needs Casey's steps)
1. Create the public GitHub repo for this action and push these files.
2. Tag a release `v1` (and `v1.0.0`) — users pin `uses: <org>/normalize-cpl-action@v1`.
3. Publish it to the GitHub Marketplace (repo → About → "Publish this
   action to the Marketplace", or via the release page). Marketplace
   listing needs a repo description, branding (already in `action.yml`:
   cpu/orange) and a `v1` major-version tag.
4. Update the `uses:` line above with the real org name.
