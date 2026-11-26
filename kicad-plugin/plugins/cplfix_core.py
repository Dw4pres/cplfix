"""CPLfix core logic — pure Python, no KiCad dependency.

This module does everything except talk to KiCad's GUI:
  * turn a list of footprints into a KiCad ASCII ``.pos`` text
    (the exact format the CPLfix API accepts, spec v1.1 §4.1), and
  * POST that text to the live CPLfix API and return the parsed result.

It deliberately contains NO rotation math. The API is the single source
of truth for every offset (JLCPCB bottom = (180 - rot + delta) % 360,
PCBWay/MacroFab = rot as-is — spec v1.1 §4.3). This module only formats
the input and reports what the API returns.

Importing this module never touches ``pcbnew`` — it is importable and
testable in plain Python. ``cplfix.py`` (the ActionPlugin wrapper) is
the only file that imports ``pcbnew``.
"""

import json
import urllib.error
import urllib.request

API_BASE_DEFAULT = "https://cplfix.com"
VALID_CMS = ("jlcpcb", "pcbway", "macrofab")


class CplfixError(Exception):
    """A user-facing CPLfix failure (bad input, network, or API error)."""


# ---------------------------------------------------------------------------
# .pos building
# ---------------------------------------------------------------------------

def build_pos_text(footprints, board_name=""):
    """Build a KiCad ASCII .pos text from footprint dicts.

    Each footprint dict needs: ref, value, package, x_mm, y_mm, rot_deg,
    side ("top" or "bottom"). Coordinates are in mm, relative to the
    board's aux origin — exactly what KiCad's own .pos export writes
    (spec v1.1 §4.1/§4.2). Rotation is degrees, as KiCad reports it.

    The API parses data lines from the right (last 4 tokens = PosX/PosY/
    Rot/Side), so value fields may contain spaces.
    """
    lines = [
        "### Module positions - created by CPLfix plugin ###",
        "## Unit = mm, Angle = deg.",
        "## Side : All",
        "# Ref Val Package PosX PosY Rot Side",
    ]
    for fp in footprints:
        side = "bottom" if str(fp["side"]).lower().startswith("bottom") else "top"
        rot = float(fp["rot_deg"]) % 360.0
        lines.append(
            "%-8s %-20s %-40s %10.4f %10.4f %8.4f  %s"
            % (
                fp["ref"],
                fp.get("value", ""),
                fp["package"],
                float(fp["x_mm"]),
                float(fp["y_mm"]),
                rot,
                side,
            )
        )
    lines.append("## End")
    if board_name:
        lines.insert(0, "### Board: %s ###" % board_name)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Reading footprints out of a pcbnew board (pcbnew passed in, not imported)
# ---------------------------------------------------------------------------

def _footprint_side(fp, pcbnew):
    """Return "top" or "bottom" for a pcbnew FOOTPRINT.

    Preferred: FOOTPRINT.GetLayer() (the placement layer). Fallback:
    the footprint's layer set — bottom only if it sits on B.Cu and not
    on F.Cu (through-hole parts sit on both, and are top by convention).
    """
    try:
        if fp.GetLayer() == pcbnew.B_Cu:
            return "bottom"
        return "top"
    except Exception:
        pass
    try:
        layers = fp.GetLayerSet()
        if layers.Contains(pcbnew.B_Cu) and not layers.Contains(pcbnew.F_Cu):
            return "bottom"
    except Exception:
        pass
    return "top"


def _footprint_package(fp):
    """Return the footprint/library item name, e.g. SOIC-8_3.9x4.9mm_P1.27mm."""
    try:
        return fp.GetFPID().GetLibItemName()
    except Exception:
        pass
    try:
        fpid = fp.GetFPIDAsString()
        return fpid.split(":")[-1] if ":" in fpid else fpid
    except Exception:
        return ""


def _footprint_rotation(fp):
    """Return the footprint rotation in degrees, normalised to [0, 360)."""
    try:
        return float(fp.GetOrientationDegrees()) % 360.0
    except Exception:
        pass
    # Older SWIG bindings: GetOrientation() returns degrees as a float.
    return float(fp.GetOrientation()) % 360.0


def footprints_from_board(board, pcbnew):
    """Convert a pcbnew BOARD into the footprint dicts build_pos_text wants.

    Positions come from FOOTPRINT.GetPosition() in KiCad internal units
    (nanometres in KiCad 6+), converted to mm and made relative to the
    board's aux origin — the same reference KiCad's own .pos export uses.
    """
    try:
        to_mm = pcbnew.ToMM
    except Exception:
        to_mm = lambda iu: iu / 1.0e6  # noqa: E731 - KiCad internal unit is nm

    try:
        aux = board.GetDesignSettings().GetAuxOrigin()
        aux_x_mm, aux_y_mm = to_mm(aux.x), to_mm(aux.y)
    except Exception:
        aux_x_mm, aux_y_mm = 0.0, 0.0

    out = []
    for fp in board.GetFootprints():
        pos = fp.GetPosition()
        out.append(
            {
                "ref": fp.GetReference(),
                "value": fp.GetValue(),
                "package": _footprint_package(fp),
                "x_mm": to_mm(pos.x) - aux_x_mm,
                "y_mm": to_mm(pos.y) - aux_y_mm,
                "rot_deg": _footprint_rotation(fp),
                "side": _footprint_side(fp, pcbnew),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Live API
# ---------------------------------------------------------------------------

def normalize_via_api(pos_text, cm, api_base=API_BASE_DEFAULT,
                      negate_bottom_x=False, timeout=30):
    """POST .pos text to the live CPLfix API; return the parsed JSON.

    Raises CplfixError with a plain-English message on any failure —
    the caller shows this to the user, never a traceback.
    """
    cm = (cm or "").strip().lower()
    if cm not in VALID_CMS:
        raise CplfixError("Unknown CM %r — pick jlcpcb, pcbway or macrofab." % cm)
    if not pos_text or not pos_text.strip():
        raise CplfixError("No placement data to normalize (board has no footprints?).")

    url = api_base.rstrip("/") + "/api/v1/normalize/" + cm
    if negate_bottom_x:
        url += "?inputNegateBottomX=true"
    req = urllib.request.Request(
        url, data=pos_text.encode("utf-8"),
        headers={
            "Content-Type": "text/plain",
            # Identify the client: Cloudflare blocks the default
            # "Python-urllib/..." User-Agent with a 1010 challenge.
            "User-Agent": "CPLfix-KiCad-Plugin/1.0 (+https://cplfix.com)",
        }, method="POST",
    )
    # Cloudflare sometimes drops a Python-urllib connection mid-body
    # (IncompleteRead); the request is a pure read of a corrected file,
    # so retrying it is safe. curl does not hit this.
    import http.client

    body = None
    last_exc = None
    for _attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            break
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
            raise CplfixError(
                "CPLfix API returned HTTP %s%s"
                % (e.code, (": " + detail) if detail else "")
            )
        except urllib.error.URLError as e:
            last_exc = e
            break
    if body is None:
        raise CplfixError(
            "Could not reach %s (%s). Check your network and try again."
            % (api_base, getattr(last_exc, "reason", last_exc))
        )
    try:
        result = json.loads(body)
    except ValueError:
        raise CplfixError("CPLfix API returned a response I could not read.")
    if not isinstance(result, dict) or "csv" not in result:
        raise CplfixError("CPLfix API returned an unexpected response.")
    return result


def summarize(result):
    """Short report dict from an API result: parts, changed, warnings."""
    matched = result.get("matchedRules") or []
    changed = sum(
        1 for m in matched
        if isinstance(m, dict) and m.get("matched") and (m.get("delta") or 0) != 0
    )
    csv_text = result.get("csv") or ""
    parts = max(len(matched), len([l for l in csv_text.splitlines() if l.strip()]) - 1)
    return {
        "parts": parts,
        "changed": changed,
        "warnings": list(result.get("warnings") or []),
    }
