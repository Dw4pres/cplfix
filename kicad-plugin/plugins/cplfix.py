"""CPLfix — KiCad ActionPlugin (KiCad 7/8/9, SWIG pcbnew runtime).

Tools -> External Plugins -> CPLfix. Reads the open board, sends its
placement to the free CPLfix API (https://cplfix.com), and saves the
corrected CPL next to the board file as ``cpl-<cm>.csv``.

No rotation math lives here — the live API is the single source of
truth for every offset (spec v1.1 §4.3). No accounts, no API key, no
payment. The API is free and ungated.

If this file is imported outside KiCad (no ``pcbnew`` module), nothing
registers and nothing crashes — the pure logic lives in ``cplfix_core``
and is tested without KiCad. Inside KiCad, a missing board or an API
failure is reported with a message box, never a traceback.
"""

import os
import sys

# The core module sits next to this file; make sure plain ``import
# cplfix_core`` works no matter how KiCad loads this plugin.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cplfix_core import (  # noqa: E402
    API_BASE_DEFAULT,
    CplfixError,
    build_pos_text,
    footprints_from_board,
    normalize_via_api,
    summarize,
)

try:
    import pcbnew
except ImportError:  # Not running inside KiCad (tests, plain python).
    pcbnew = None

try:
    import wx
except ImportError:
    wx = None


CM_CHOICES = ["jlcpcb", "pcbway", "macrofab"]
CM_LABELS = {
    "jlcpcb": "JLCPCB",
    "pcbway": "PCBWay",
    "macrofab": "MacroFab",
}


def _show_message(title, text):
    if wx is not None:
        wx.MessageBox(text, title, wx.OK | wx.ICON_INFORMATION)
    else:
        print("[%s] %s" % (title, text))


def _show_error(title, text):
    if wx is not None:
        wx.MessageBox(text, title, wx.OK | wx.ICON_ERROR)
    else:
        print("[%s] ERROR: %s" % (title, text), file=sys.stderr)


class _OptionsDialog(wx.Dialog if wx is not None else object):
    """Small dialog: target CM + the KiCad "negative X on bottom" option."""

    def __init__(self, parent):
        super().__init__(parent, title="CPLfix — Normalize CPL")
        self.cm_choice = wx.Choice(self, choices=[CM_LABELS[c] for c in CM_CHOICES])
        self.cm_choice.SetSelection(0)  # JLCPCB
        self.negate_check = wx.CheckBox(
            self, label="Input used KiCad \u201cnegative X on bottom\u201d export"
        )
        ok_btn = wx.Button(self, wx.ID_OK, "Normalize")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Cancel")

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label="Target CM:"), 0, wx.ALL, 8)
        sizer.Add(self.cm_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        sizer.Add(self.negate_check, 0, wx.ALL, 8)
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.Add(ok_btn, 0, wx.ALL, 8)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 8)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT)
        self.SetSizerAndFit(sizer)

    @property
    def cm(self):
        return CM_CHOICES[self.cm_choice.GetSelection()]

    @property
    def negate_bottom_x(self):
        return self.negate_check.GetValue()


def run_normalize():
    """The whole flow, callable from the plugin and from tests with stubs."""
    if pcbnew is None:
        raise CplfixError(
            "CPLfix runs inside KiCad's PCB editor (Tools > External Plugins). "
            "pcbnew is not available here."
        )
    board = pcbnew.GetBoard()
    if board is None:
        raise CplfixError("No board is open. Open a .kicad_pcb file first.")

    cm = "jlcpcb"
    negate_bottom_x = False
    if wx is not None:
        dlg = _OptionsDialog(None)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return None  # User cancelled — not an error.
            cm = dlg.cm
            negate_bottom_x = dlg.negate_bottom_x
        finally:
            dlg.Destroy()

    footprints = footprints_from_board(board, pcbnew)
    if not footprints:
        raise CplfixError("The open board has no footprints to normalize.")
    pos_text = build_pos_text(footprints)

    result = normalize_via_api(
        pos_text, cm, api_base=API_BASE_DEFAULT, negate_bottom_x=negate_bottom_x
    )
    summary = summarize(result)

    board_path = board.GetFileName() or ""
    board_dir = os.path.dirname(board_path) or os.getcwd()
    board_stem = os.path.splitext(os.path.basename(board_path))[0] or "board"
    out_csv = os.path.join(board_dir, "cpl-%s.csv" % cm)
    with open(out_csv, "w", encoding="utf-8") as f:
        f.write(result["csv"])
    # Keep the exact input we sent, for reproducing a result by hand.
    with open(os.path.join(board_dir, board_stem + ".cplfix.pos"), "w",
              encoding="utf-8") as f:
        f.write(pos_text)

    lines = [
        "Normalized %d part(s) for %s." % (summary["parts"], CM_LABELS[cm]),
        "%d part(s) had their rotation changed." % summary["changed"],
        "",
        "Saved: %s" % out_csv,
    ]
    for w in summary["warnings"][:5]:
        lines.append("Warning: %s" % w)
    if len(summary["warnings"]) > 5:
        lines.append("(%d more warning(s) — see the file.)"
                     % (len(summary["warnings"]) - 5))
    lines.append("")
    lines.append("Always verify every part in your CM's placement preview "
                 "before ordering — it's the final authority.")
    _show_message("CPLfix", "\n".join(lines))
    return {"out_csv": out_csv, "summary": summary}


if pcbnew is not None:

    class CplfixPlugin(pcbnew.ActionPlugin):
        def defaults(self):
            self.name = "CPLfix — Normalize CPL Rotations"
            self.category = "Fabrication"
            self.description = (
                "Send the open board's placement to cplfix.com and save "
                "a corrected CPL for JLCPCB, PCBWay or MacroFab."
            )
            self.show_toolbar_button = False

        def Run(self):
            try:
                run_normalize()
            except CplfixError as e:
                _show_error("CPLfix", str(e))
            except Exception as e:  # Never show KiCad a traceback.
                _show_error("CPLfix",
                            "Something went wrong: %s" % e)

    CplfixPlugin().register()
