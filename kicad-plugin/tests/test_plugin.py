"""Tests for the CPLfix KiCad plugin core.

No KiCad is installed here, so pcbnew is stubbed: fake FOOTPRINT /
BOARD objects with the same methods the real API has (verified against
https://docs.kicad.org/doxygen-python-6.0/classpcbnew_1_1FOOTPRINT.html
and dev-docs.kicad.org/en/addons).

Run:  python3 -m unittest discover -s tests -v
from app/kicad-plugin/.

One test is live: it POSTs the built .pos text to the production API
at https://cplfix.com and checks the hand-checked rows. It needs
network; the rest run offline.
"""

import json
import os
import sys
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins"))

from cplfix_core import (  # noqa: E402
    API_BASE_DEFAULT,
    CplfixError,
    build_pos_text,
    footprints_from_board,
    normalize_via_api,
    summarize,
)

# The sample board (app/samples/sample.pos): ref, value, package,
# x_mm, y_mm, rot_deg, side. Positions are in KiCad internal units
# (nm) in the fake board, converted by the code under test.
SAMPLE_PARTS = [
    ("U1", "LM358", "SOIC-8_3.9x4.9mm_P1.27mm", 10.0, 20.0, 0.0, "top"),
    ("U2", "LM358", "SOIC-8_3.9x4.9mm_P1.27mm", 30.0, 20.0, 90.0, "bottom"),
    ("Q1", "AO3400A", "SOT-23-5", 40.0, 10.0, 0.0, "bottom"),
    ("Q2", "MMBT3904", "SOT-23-3", 50.0, 10.0, 0.0, "top"),
    ("D1", "1N4148", "D_SOD-323", 15.0, 25.0, 180.0, "bottom"),
    ("U3", "STM32F103", "QFN-48_7x7mm_P0.5mm", 60.0, 30.0, 90.0, "top"),
    ("J1", "USB C", "USB_C_Receptacle_HRO_TYPE-C-31-M-12", 70.0, 40.0, 0.0, "top"),
    ("C1", "10uF 50V", "C_0603_1608Metric", 12.0, 22.0, 180.0, "top"),
    ("R1", "4.7k", "R_0603_1608Metric", 14.0, 24.0, 90.0, "bottom"),
]

EXPECTED_ROWS = {
    "U1": "U1,10,-20,Top,270",
    "U2": "U2,30,-20,Bottom,0",
    "Q1": "Q1,40,-10,Bottom,90",
}


class _FakeLibId:
    def __init__(self, name):
        self._name = name

    def GetLibItemName(self):
        return self._name


class _FakePoint:
    def __init__(self, x_nm, y_nm):
        self.x = x_nm
        self.y = y_nm


class _FakeLayerSet:
    def __init__(self, layers):
        self._layers = set(layers)

    def Contains(self, layer):
        return layer in self._layers


class _FakeFootprint:
    """Mimics the pcbnew FOOTPRINT methods the plugin uses."""

    def __init__(self, ref, value, package, x_mm, y_mm, rot, side, pcbnew):
        self._ref, self._value = ref, value
        self._fpid = _FakeLibId(package)
        self._pos = _FakePoint(int(x_mm * 1e6), int(y_mm * 1e6))
        self._rot = rot
        self._side = side
        self._pcbnew = pcbnew

    def GetReference(self):
        return self._ref

    def GetValue(self):
        return self._value

    def GetFPID(self):
        return self._fpid

    def GetFPIDAsString(self):
        return "Library:%s" % self._fpid.GetLibItemName()

    def GetPosition(self):
        return self._pos

    def GetOrientationDegrees(self):
        return self._rot

    def GetOrientation(self):
        return self._rot

    def GetLayer(self):
        return self._pcbnew.B_Cu if self._side == "bottom" else self._pcbnew.F_Cu

    def GetLayerSet(self):
        layer = self._pcbnew.B_Cu if self._side == "bottom" else self._pcbnew.F_Cu
        return _FakeLayerSet([layer])


class _FakeDesignSettings:
    def GetAuxOrigin(self):
        return _FakePoint(0, 0)


class _FakeBoard:
    def __init__(self, footprints):
        self._fps = footprints

    def GetFootprints(self):
        return self._fps

    def GetDesignSettings(self):
        return _FakeDesignSettings()

    def GetFileName(self):
        return "/tmp/fake-board.kicad_pcb"


class _FakePcbnew:
    F_Cu = 0
    B_Cu = 31

    @staticmethod
    def ToMM(iu):
        return iu / 1.0e6


def make_fake_board():
    pcbnew = _FakePcbnew()
    fps = [_FakeFootprint(*p, pcbnew) for p in SAMPLE_PARTS]
    return _FakeBoard(fps), pcbnew


class TestPosBuilding(unittest.TestCase):
    def test_fake_board_matches_sample_pos(self):
        """footprints_from_board + build_pos_text must reproduce the
        sample board's .pos rows, so the API sees exactly what KiCad's
        own .pos export would write."""
        board, pcbnew = make_fake_board()
        fps = footprints_from_board(board, pcbnew)
        self.assertEqual(len(fps), 9)
        self.assertEqual(fps[0]["ref"], "U1")
        self.assertEqual(fps[0]["package"], "SOIC-8_3.9x4.9mm_P1.27mm")
        self.assertAlmostEqual(fps[0]["x_mm"], 10.0)
        self.assertAlmostEqual(fps[0]["y_mm"], 20.0)
        self.assertEqual(fps[1]["side"], "bottom")
        self.assertEqual(fps[6]["value"], "USB C")  # value with a space
        pos = build_pos_text(fps)
        self.assertIn("## Unit = mm, Angle = deg.", pos)
        for ref, _val, pkg, x, y, rot, side in SAMPLE_PARTS:
            row = [l for l in pos.splitlines() if l.startswith(ref + " ")]
            self.assertEqual(len(row), 1, ref)
            toks = row[0].split()
            self.assertEqual(toks[-4:], ["%.4f" % x, "%.4f" % y, "%.4f" % rot, side])
            self.assertIn(pkg, row[0])

    def test_no_pcbnew_needed_for_core(self):
        """cplfix_core imports and builds .pos with no pcbnew present."""
        self.assertNotIn("pcbnew", sys.modules)
        pos = build_pos_text(
            [{"ref": "U1", "value": "LM358", "package": "SOIC-8",
              "x_mm": 10, "y_mm": 20, "rot_deg": 0, "side": "top"}]
        )
        self.assertIn("U1", pos)

    def test_bad_cm_rejected_without_network(self):
        with self.assertRaises(CplfixError):
            normalize_via_api("U1 1 SOIC-8 10 20 0 top\n", "notacm")

    def test_empty_pos_rejected(self):
        with self.assertRaises(CplfixError):
            normalize_via_api("   \n", "jlcpcb")


class TestLiveApi(unittest.TestCase):
    def test_sample_board_hand_checked_rows(self):
        """Live check: the .pos text the plugin builds, POSTed to the
        production API, returns the hand-checked rows."""
        board, pcbnew = make_fake_board()
        pos = build_pos_text(footprints_from_board(board, pcbnew))
        result = normalize_via_api(pos, "jlcpcb", api_base=API_BASE_DEFAULT)
        rows = {l.split(",")[0]: l for l in result["csv"].splitlines()[1:]}
        for ref, expected in EXPECTED_ROWS.items():
            self.assertEqual(rows[ref], expected, ref)
        summary = summarize(result)
        self.assertEqual(summary["parts"], 9)
        self.assertGreater(summary["changed"], 0)


if __name__ == "__main__":
    unittest.main()
