# SPDX-License-Identifier: Apache-2.0
"""Hand-checked tests for truth_core (truth-1). MV2 of Munim, Inc. Made with
AI agents working in MV2's name. Apache-2.0."""
import datetime as dt
import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import truth_core as c  # noqa: E402

UTC = dt.timezone.utc


def z(y, m, d, h, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=UTC)


# ---------------------------------------------------------------- a tiny xlsx built by hand
HEADER = ["Station Code", "Station Name", "Unit Name", "Seasonal Max MW", "Available MW", "MW Reduction",
          "Fuel Type", "Outage/Derate Start", "Outage/Derate End", "County", "Resource Entity"]
DATA_ROWS = [
    ["GENERATION RESOURCE AND ENERGY STORAGE RESOURCE OUTAGES AND DERATES"],
    HEADER,
    ["MCSES", "MOUNTAIN CREEK SES", "UNIT8", 568, 200, 368, "NG", 44241.479166666664, 44242.125, "DALLAS",
     "SOME POWER LLC"],
    ["WAP", "WA PARISH", "WAP_G4", 552, 0, 552, "COAL", "2/15/21 6:05 AM", "2/16/21 1:00 PM", "Fort Bend County",
     "NRG TEXAS POWER LLC"],
    [None, None, None, 300, 0, 300, None, "2/15/21 2:00 AM", None, None, None],
    ["Total", None, None, None, None, 1220],
]


def col_letter(i):
    return chr(65 + i)


def build_xlsx(sheets):
    shared, sidx = [], {}

    def sheet_xml(rows):
        out = []
        for ri, row in enumerate(rows):
            cells = []
            for ci, v in enumerate(row):
                if v is None:
                    continue
                ref = "%s%d" % (col_letter(ci), ri + 1)
                if isinstance(v, str):
                    if v not in sidx:
                        sidx[v] = len(shared)
                        shared.append(v)
                    cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, sidx[v]))
                else:
                    cells.append('<c r="%s"><v>%r</v></c>' % (ref, v))
            out.append('<row r="%d">%s</row>' % (ri + 1, "".join(cells)))
        return ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % "".join(out))

    bodies = [sheet_xml(rows) for _, rows in sheets]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/workbook.xml",
                    '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/'
                    'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships"><sheets>%s</sheets></workbook>' % "".join(
                        '<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (n, i + 1, i + 1)
                        for i, (n, _) in enumerate(sheets)))
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                    'package/2006/relationships">%s</Relationships>' % "".join(
                        '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                        'relationships/worksheet" Target="%s"/>' % (
                            i + 1, ("worksheets/sheet%d.xml" if i == 0 else "/xl/worksheets/sheet%d.xml") % (i + 1))
                        for i in range(len(sheets))))
        for i, body in enumerate(bodies):
            zf.writestr("xl/worksheets/sheet%d.xml" % (i + 1), body)
        zf.writestr("xl/sharedStrings.xml",
                    '<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/'
                    'spreadsheetml/2006/main">%s</sst>' % "".join(
                        "<si><t>%s</t></si>" % s.replace("&", "&amp;").replace("<", "&lt;") for s in shared))
    return buf.getvalue()


# ---------------------------------------------------------------- records and trips for matching
REC_MAP = {"seasonal_mw": 0, "available_mw": 1, "fuel": 2, "start": 3, "end": 4, "county": 5}


def rec(county, fuel, size, avail, start, end=None):
    r = c.make_record([size, avail, fuel, start, end, county], REC_MAP)
    assert r is not None
    return r


def records():
    return [
        rec("DALLAS", "NG", 568, 200, "02/14/2021 11:30", "02/15/2021 03:00"),      # A 17:30Z
        rec("FORT BEND", "COAL", 552, 0, "02/15/2021 06:05", "02/16/2021 13:00"),   # B 12:05Z
        rec("", "", 300, 0, "02/15/2021 02:00"),                                     # C redacted
        rec("DALLAS", "NG", 500, 0, "02/15/2021 11:00", "02/15/2021 23:00"),        # E 17:00Z
        rec("DALLAS", "WIND", 200, 0, "02/14/2021 12:00"),                           # F wind
    ]


def trips():
    return [
        {"county_n": "DALLAS", "cap": 500.0, "start_utc": z(2021, 2, 14, 18)},     # t1
        {"county_n": "FORTBEND", "cap": 600.0, "start_utc": z(2021, 2, 15, 12)},   # t2
        {"county_n": "DALLAS", "cap": 100.0, "start_utc": z(2021, 2, 14, 18)},     # t3
        {"county_n": "TRAVIS", "cap": 300.0, "start_utc": z(2021, 2, 16, 0)},      # t4
        {"county_n": "", "cap": 300.0, "start_utc": z(2021, 2, 15, 8)},            # t5
        {"county_n": "DALLAS", "cap": 500.0, "start_utc": z(2021, 2, 13, 18)},     # t6
    ]


class TestCells(unittest.TestCase):
    def test_col_index(self):
        self.assertEqual(c.col_index("A1"), 0)
        self.assertEqual(c.col_index("C7"), 2)
        self.assertEqual(c.col_index("AA3"), 26)
        self.assertEqual(c.col_index("AZ1"), 51)
        self.assertIsNone(c.col_index(None))

    def test_parse_local(self):
        self.assertEqual(c.parse_local("2/14/21 11:30 AM"), dt.datetime(2021, 2, 14, 11, 30))
        self.assertEqual(c.parse_local("2/16/21 1:00 PM"), dt.datetime(2021, 2, 16, 13, 0))
        self.assertEqual(c.parse_local(44241.479166666664), dt.datetime(2021, 2, 14, 11, 30))
        self.assertEqual(c.parse_local("44242.125"), dt.datetime(2021, 2, 15, 3, 0))
        self.assertEqual(c.parse_local("02/15/2021 06:05"), dt.datetime(2021, 2, 15, 6, 5))
        self.assertIsNone(c.parse_local("garbage"))
        self.assertIsNone(c.parse_local(12))
        self.assertIsNone(c.parse_local(None))
        self.assertIsNone(c.parse_local("  "))

    def test_central_to_utc(self):
        self.assertEqual(c.central_to_utc(dt.datetime(2021, 2, 14, 23, 0)), z(2021, 2, 15, 5))
        self.assertIsNone(c.central_to_utc(None))

    def test_norm_county(self):
        self.assertEqual(c.norm_county("Fort Bend County"), "FORTBEND")
        self.assertEqual(c.norm_county("DE WITT"), "DEWITT")
        self.assertEqual(c.norm_county("DeWitt"), "DEWITT")
        self.assertEqual(c.norm_county(None), "")

    def test_fuel_group(self):
        self.assertEqual(c.fuel_group("NG"), "GAS")
        self.assertEqual(c.fuel_group("SCGT90"), "GAS")
        self.assertEqual(c.fuel_group("CCGT90"), "GAS")
        self.assertEqual(c.fuel_group("COAL"), "COAL")
        self.assertEqual(c.fuel_group("LIG"), "COAL")
        self.assertEqual(c.fuel_group("WIND"), "NONFOSSIL")
        self.assertEqual(c.fuel_group("NUC"), "NONFOSSIL")
        self.assertEqual(c.fuel_group("LANDFILL GAS"), "NONFOSSIL")
        self.assertEqual(c.fuel_group(""), "UNKNOWN")
        self.assertEqual(c.fuel_group("DFO"), "OIL")
        self.assertEqual(c.fuel_group("XYZ"), "OTHER")

    def test_to_num(self):
        self.assertEqual(c.to_num("1,234.5"), 1234.5)
        self.assertEqual(c.to_num(7), 7.0)
        self.assertIsNone(c.to_num("n/a"))
        self.assertIsNone(c.to_num(None))

    def test_entity_like(self):
        self.assertTrue(c.entity_like("SOME POWER LLC"))
        self.assertTrue(c.entity_like("NRG TEXAS POWER (RE)"))
        self.assertFalse(c.entity_like("FORT BEND"))

    def test_map_header(self):
        m = c.map_header(HEADER)
        self.assertEqual(m, {"station_code": 0, "station": 1, "unit": 2, "seasonal_mw": 3, "available_mw": 4,
                             "reduction_mw": 5, "fuel": 6, "start": 7, "end": 8, "county": 9, "entity": 10})
        self.assertTrue(c.header_ok(m))
        self.assertFalse(c.header_ok(c.map_header(["GENERATION RESOURCE OUTAGES"])))


class TestXlsx(unittest.TestCase):
    def test_read_and_parse(self):
        data = build_xlsx([("Notes", [["Notes about the data"]]), ("Data", DATA_ROWS)])
        sheets, d1904 = c.read_xlsx(data)
        self.assertFalse(d1904)
        self.assertEqual([s[0] for s in sheets], ["Notes", "Data"])
        self.assertEqual(sheets[1][1][1], HEADER)
        self.assertEqual(sheets[1][1][2][3], 568.0)
        self.assertEqual(sheets[1][1][4][:4], [None, None, None, 300.0])
        recs, info = c.parse_records(sheets, d1904)
        self.assertEqual(len(recs), 3)
        self.assertEqual(info["sheets"][0]["mode"], None)
        self.assertEqual(info["sheets"][1]["mode"], "header")
        self.assertEqual(info["sheets"][1]["header_row"], 1)
        self.assertEqual(info["sheets"][1]["records"], 3)
        a, b, r3 = recs
        self.assertEqual(a["start_utc"], z(2021, 2, 14, 17, 30))
        self.assertEqual(a["end_utc"], z(2021, 2, 15, 9))
        self.assertEqual(a["fuel_group"], "GAS")
        self.assertTrue(a["fossil"])
        self.assertEqual(a["county_n"], "DALLAS")
        self.assertFalse(a["full"])
        self.assertEqual(a["reduction_mw"], 368.0)
        self.assertEqual(a["unit"], "UNIT8")
        self.assertEqual(b["start_utc"], z(2021, 2, 15, 12, 5))
        self.assertEqual(b["end_utc"], z(2021, 2, 16, 19))
        self.assertEqual(b["county_n"], "FORTBEND")
        self.assertEqual(b["fuel_group"], "COAL")
        self.assertTrue(b["full"])
        self.assertTrue(r3["redacted"])
        self.assertFalse(r3["fossil"])
        self.assertEqual(r3["start_utc"], z(2021, 2, 15, 8))
        self.assertIsNone(r3["end_utc"])

    def test_fallback_layout(self):
        rows = [["MCSES", "MOUNTAIN CREEK SES", "UNIT8", "568", "200", "368", "NG", "2/14/21 11:30 AM",
                 "2/15/21 3:00 AM", "DALLAS", "SOME POWER LLC"]] * 3
        mode, hi, m = c.find_layout(rows)
        self.assertEqual(mode, "fallback")
        self.assertIsNone(hi)
        self.assertEqual((m["county"], m["entity"]), (9, 10))
        rows2 = [r[:9] + ["SOME POWER LLC", "DALLAS"] for r in rows]
        self.assertEqual(c.find_layout(rows2)[2]["county"], 10)
        recs, info = c.parse_records([("only", rows2)])
        self.assertEqual(len(recs), 3)
        self.assertEqual(info["fallback_sheet"], "only")
        self.assertEqual(recs[0]["county_n"], "DALLAS")
        self.assertEqual(recs[0]["start_utc"], z(2021, 2, 14, 17, 30))


class TestMatching(unittest.TestCase):
    def test_records(self):
        r = records()
        self.assertEqual([x["reduction_mw"] for x in r], [368.0, 552.0, 300.0, 500.0, 200.0])
        self.assertEqual(r[3]["start_utc"], z(2021, 2, 15, 17))
        self.assertEqual(r[3]["end_utc"], z(2021, 2, 16, 5))
        self.assertEqual([x["full"] for x in r], [False, True, True, True, True])

    def test_cap_ok(self):
        self.assertTrue(c.cap_ok(568, 500))
        self.assertFalse(c.cap_ok(568, 100))
        self.assertTrue(c.cap_ok(400, 100))
        self.assertTrue(c.cap_ok(25, 100))
        self.assertFalse(c.cap_ok(24, 100))
        self.assertTrue(c.cap_ok(None, 100))

    def test_matches(self):
        r, t = records(), trips()
        self.assertEqual(c.matches(t[0], r), [0])
        self.assertEqual(c.matches(t[1], r), [1])
        self.assertEqual(c.matches(t[2], r), [])
        self.assertEqual(c.matches(t[2], r, check_cap=False), [0])
        self.assertEqual(c.matches(t[0], r, shift_h=24.0), [3])

    def test_precision(self):
        r, t = records(), trips()
        self.assertEqual(c.precision(t, r), (2, 4))
        self.assertEqual(c.precision(t, r, check_cap=False), (3, 4))
        self.assertEqual(c.precision(t, r, tol_h=0.25), (1, 4))
        self.assertEqual(c.precision(t, r, shift_h=-24.0), (0, 4))
        self.assertEqual(c.precision(t, r, shift_h=24.0), (1, 4))
        self.assertEqual(c.placebo_precision(t, r), (1, 8))

    def test_recall(self):
        r, t = records(), trips()
        u = [{"county_n": "DALLAS", "cap": 550.0, "hard": {c.ehour(z(2021, 2, 15, 14))}},
             {"county_n": "FORTBEND", "cap": 600.0, "hard": {c.ehour(z(2021, 2, 15, 11))}}]
        self.assertEqual(c.recall(r, u, t), (1, 2))
        u[0]["hard"] = {c.ehour(z(2021, 2, 15, 17))}   # the start hour itself does not count
        self.assertEqual(c.recall(r, u, t), (1, 1))

    def test_curve(self):
        r = records()
        h0 = c.ehour(z(2021, 2, 15, 12))
        self.assertEqual(c.ercot_curve(r, h0, 8), [552.0] * 5 + [1052.0] * 3)
        self.assertEqual(c.ercot_curve(r, h0, 8, fossil_only=False), [1052.0] * 5 + [1552.0] * 3)

    def test_pearson(self):
        self.assertAlmostEqual(c.pearson([1, 2, 3], [2, 4, 6]), 1.0)
        self.assertAlmostEqual(c.pearson([1, 2, 3], [3, 2, 1]), -1.0)
        self.assertIsNone(c.pearson([1, 1, 1], [1, 2, 3]))
        self.assertIsNone(c.pearson([1, 2], [1, 2]))

    def test_score(self):
        self.assertEqual(c.score((25, 30), (5, 50), (12, 20), 0.85),
                         {"V1": True, "V2": True, "V3": True, "V4": True})
        self.assertEqual(c.score((20, 30), (15, 30), (9, 20), 0.79),
                         {"V1": False, "V2": False, "V3": False, "V4": False})
        self.assertEqual(c.score((10, 29), (0, 0), (5, 19), None),
                         {"V1": None, "V2": None, "V3": None, "V4": None})
        self.assertEqual(c.score((3, 30), (0, 10), (0, 20), 0.8),
                         {"V1": False, "V2": False, "V3": True, "V4": True})


if __name__ == "__main__":
    unittest.main(verbosity=2)
