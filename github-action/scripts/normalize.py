#!/usr/bin/env python3
"""CPLfix GitHub Action runner — Python 3 stdlib only.

Finds placement files, POSTs each to the free CPLfix API, and writes
the normalized CSV next to the source file. No accounts, no API key,
no payment, no third-party packages: python3 ships on every
GitHub-hosted runner (ubuntu/windows/macos), which is why this is
Python instead of a shell/curl script (curl + jq quoting and glob
handling differ per shell/OS; Node would need an npm install step).

Exit behaviour (documented in the README):
  * Normalization WARNINGS never fail the run — they are counted,
    printed, and reported as an output.
  * The run fails ONLY on API errors (non-200, network failure) or
    unparseable files. A failed file aborts the run with a clear
    message so a bad placement file can never silently ship.

Rotation math lives entirely in the API (spec v1.1 §4.3); this script
only moves files and reports what the API returns.
"""

import argparse
import glob
import http.client
import json
import os
import sys
import urllib.error
import urllib.request

VALID_CMS = ("jlcpcb", "pcbway", "macrofab")
USER_AGENT = "CPLfix-GitHub-Action/1.0 (+https://cplfix.com)"


def fail(message):
    print("::error::%s" % message)
    sys.exit(1)


def post_normalize(api_base, cm, text, timeout=60):
    """POST one placement file; return the parsed API JSON."""
    url = api_base.rstrip("/") + "/api/v1/normalize/" + cm
    req = urllib.request.Request(
        url, data=text.encode("utf-8"),
        headers={"Content-Type": "text/plain", "User-Agent": USER_AGENT},
        method="POST",
    )
    last_exc = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except http.client.HTTPException as e:
            # Dropped mid-body / remote closed the connection; retry.
            # (IncompleteRead and RemoteDisconnected both land here,
            # and neither is a URLError, so they need this branch.)
            last_exc = e
            continue
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            fail("CPLfix API returned HTTP %s for %s%s"
                 % (e.code, url, (": " + detail) if detail else ""))
        except urllib.error.URLError as e:
            last_exc = e
            break
    fail("Could not reach %s (%s)" % (api_base, getattr(last_exc, "reason", last_exc)))


def set_output(name, value):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("%s=%s\n" % (name, value))


def append_summary(lines):
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description="Normalize CPL files via cplfix.com")
    ap.add_argument("--cm", default="jlcpcb")
    ap.add_argument("--files", default="**/*.pos")
    ap.add_argument("--api-base", default="https://cplfix.com")
    ap.add_argument("--output-suffix", default=".normalized.csv")
    args = ap.parse_args()

    cm = args.cm.strip().lower()
    if cm not in VALID_CMS:
        fail("Unknown cm %r — pick jlcpcb, pcbway or macrofab." % args.cm)

    paths = sorted(
        p for pattern in args.files.split("\n") if pattern.strip()
        for p in glob.glob(pattern.strip(), recursive=True)
        if os.path.isfile(p)
    )
    if not paths:
        fail("No placement files matched %r." % args.files)

    total_changed = 0
    total_warnings = 0
    summary_lines = ["## CPLfix — %s" % cm, ""]
    for path in paths:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
        if not text.strip():
            fail("Unparseable file (empty): %s" % path)
        result = post_normalize(args.api_base, cm, text)
        if not isinstance(result, dict) or "csv" not in result:
            fail("CPLfix API returned an unexpected response for %s." % path)
        matched = result.get("matchedRules") or []
        changed = sum(
            1 for m in matched
            if isinstance(m, dict) and m.get("matched") and (m.get("delta") or 0) != 0
        )
        warnings = list(result.get("warnings") or [])
        total_changed += changed
        total_warnings += len(warnings)
        stem, _ext = os.path.splitext(path)
        out_path = stem + args.output_suffix
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(result["csv"])
        line = "- `%s` → `%s`: %d part(s), %d rotation(s) changed" % (
            path, out_path, len(matched), changed)
        print(line[2:])
        summary_lines.append(line)
        for w in warnings:
            print("  warning (%s): %s" % (path, w))
            summary_lines.append("  - warning (%s): %s" % (path, w))

    print("Normalized %d file(s): %d rotation(s) changed, %d warning(s)."
          % (len(paths), total_changed, total_warnings))
    append_summary(summary_lines)
    set_output("files-normalized", len(paths))
    set_output("parts-changed", total_changed)
    set_output("warnings", total_warnings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
