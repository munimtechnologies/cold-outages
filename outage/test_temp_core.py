# SPDX-License-Identifier: Apache-2.0
"""Tests for temp_core. Every expected value was worked out by hand.
MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0."""
import gzip
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import temp_core as c  # noqa: E402


def idx(a):
    return np.nonzero(a)[0].tolist()


class TestRiskTrip(unittest.TestCase):
    SERIES = [80, 80, 80, 90, 40, 0, 0, 0, 0, 0, 0, 10, 50, 80, 80, 0, 0, 0, 0, 0]

    def test_abrupt(self):
        risk, trip = c.risk_trip(self.SERIES, 100.0, 0.3, 6)
        self.assertEqual(idx(risk), [3, 4, 5])
        self.assertEqual(idx(trip), [5])

    def test_stage1_same_here(self):
        risk, trip = c.risk_trip(self.SERIES, 100.0, 0.02, 6)
        self.assertEqual(idx(risk), [3, 4, 5])
        self.assertEqual(idx(trip), [5])

    def test_slow_ramp(self):
        loads = [80, 80, 80, 20, 0, 0, 0, 0, 0, 0]
        risk, trip = c.risk_trip(loads, 100.0, 0.3, 6)
        self.assertEqual(idx(risk), [3])
        self.assertEqual(idx(trip), [])
        risk, trip = c.risk_trip(loads, 100.0, 0.02, 6)
        self.assertEqual(idx(risk), [3, 4])
        self.assertEqual(idx(trip), [4])

    def test_no_double_count(self):
        loads = [80, 80, 80, 80, 0, 0, 0, 0, 0, 0, 0]
        risk, trip = c.risk_trip(loads, 100.0, 0.02, 6)
        self.assertEqual(idx(risk), [3, 4])
        self.assertEqual(idx(trip), [4])

    def test_long_rule(self):
        loads = [80, 80, 80, 0, 0, 0, 0, 0, 0, 50, 80, 80, 80, 80, 80, 80, 80, 80, 80, 80, 80]
        risk, trip = c.risk_trip(loads, 100.0, 0.3, 6)
        self.assertEqual(idx(trip), [3])
        risk, trip = c.risk_trip(loads, 100.0, 0.3, 12)
        self.assertEqual(idx(risk), [3])
        self.assertEqual(idx(trip), [])

    def test_small_or_short(self):
        risk, trip = c.risk_trip(self.SERIES, 20.0, 0.3, 6)
        self.assertEqual(idx(risk), [])
        risk, trip = c.risk_trip([80, 80, 80, 0, 0], 100.0, 0.3, 6)
        self.assertEqual(idx(risk), [])
        self.assertEqual(len(risk), 5)


class TestCapAndClass(unittest.TestCase):
    def test_cap(self):
        self.assertEqual(c.cap_np(list(range(1, 21))), 19.0)
        self.assertEqual(c.cap_np(list(range(1, 22))), 20.0)
        self.assertEqual(c.cap_np([0, 5, 3]), 5.0)
        self.assertEqual(c.cap_np([0, 0]), 0.0)

    def test_unit_class(self):
        self.assertEqual(c.unit_class([("BIT", "ST", 500)]), "COAL")
        self.assertEqual(c.unit_class([("NG", "CT", 200), ("NG", "CA", 100)]), "GAS_CC")
        self.assertEqual(c.unit_class([("NG", "GT", 80)]), "GAS_CT")
        self.assertEqual(c.unit_class([("NG", "ST", 300), ("BIT", "ST", 100)]), "GAS_ST")
        self.assertEqual(c.unit_class([("NG", "IC", 30)]), "GAS_OTHER")
        self.assertEqual(c.unit_class([("NG", None, 30)]), "GAS_OTHER")
        self.assertEqual(c.unit_class([("NG", "GT", 50), ("BIT", "ST", 50)]), "OTHER")
        self.assertEqual(c.unit_class([("DFO", "GT", 20)]), "OIL")
        self.assertEqual(c.unit_class([]), "OTHER")
        self.assertEqual(c.unit_class([(None, "ST", 20)]), "OTHER")


class TestTemperature(unittest.TestCase):
    def test_bins(self):
        got = c.temp_bin([-25, -20, -10.1, 14.9, 15, 35, 40, float("nan")]).tolist()
        self.assertEqual(got, [0, 1, 2, 7, 8, 12, 12, -1])
        self.assertEqual(c.N_BINS, 13)
        self.assertEqual(c.temp_bin([-10, -5, 0, 10, 19.9, 20]).tolist(), [3, 4, 5, 7, 8, 9])

    def test_parse(self):
        text = ("2016  1  1  0   -56   -72 10204   290    46     8 -9999 -9999\n"
                "2016  1  1  1 -9999   -72 10204   290    46     8 -9999 -9999\n"
                "2016  3  1 23   125    50 10150   200    30     4     0 -9999\n"
                "2016 12 31 23   -10   -20 10150   200    30     4     0 -9999\n"
                "2015 12 31 23   300   -20 10150   200    30     4     0 -9999\n"
                "junk line\n")
        for data in (text, text.encode("ascii"), gzip.compress(text.encode("ascii"))):
            t = c.parse_isd_lite(data, 2016)
            self.assertEqual(len(t), 8784)
            self.assertAlmostEqual(float(t[0]), -5.6, places=5)
            self.assertTrue(math.isnan(t[1]))
            # 1 March 2016 is day 60 (31 + 29), hour 23 -> 60*24 + 23 = 1463
            self.assertAlmostEqual(float(t[1463]), 12.5, places=5)
            self.assertAlmostEqual(float(t[8783]), -1.0, places=5)
            self.assertEqual(int(np.sum(~np.isnan(t))), 3)

    def test_year_hours(self):
        self.assertEqual(c.year_hours(2016), 8784)
        self.assertEqual(c.year_hours(2017), 8760)
        self.assertEqual(c.year_hours(2024), 8784)

    def test_fill_gaps(self):
        n = float("nan")
        t = np.array([1, n, 3, n, n, n, 7, n, n, n, n, n, 13], dtype=np.float32)
        got = c.fill_gaps(t).tolist()
        # idx1: tie between 1 (earlier) and 3 -> 1. idx3: 3. idx4: 3 (dist 2, earlier
        # wins over 7 at dist 2). idx5: 7. idx7: 7. idx8: 7. idx9: none within 2.
        # idx10: 13 (dist 2). idx11: 13.
        want = [1, 1, 3, 3, 3, 7, 7, 7, 7, None, 13, 13, 13]
        for a, b in zip(got, want):
            if b is None:
                self.assertTrue(math.isnan(a))
            else:
                self.assertEqual(a, b)

    def test_shifted(self):
        prev = np.array([1, 2, 3, 4], dtype=np.float32)
        cur = np.array([5, 6, 7], dtype=np.float32)
        self.assertEqual(c.shifted_temp(prev, cur, 2).tolist(), [3, 4, 5])
        got = c.shifted_temp(None, cur, 2).tolist()
        self.assertTrue(math.isnan(got[0]) and math.isnan(got[1]))
        self.assertEqual(got[2], 5)
        got = c.shifted_temp(prev, cur, 5).tolist()
        self.assertTrue(math.isnan(got[0]))
        self.assertEqual(got[1:], [1, 2])


class TestStations(unittest.TestCase):
    def test_haversine(self):
        self.assertAlmostEqual(float(c.haversine_km(0.0, 0.0, 0.0, 1.0)), 111.19, places=1)
        self.assertAlmostEqual(float(c.haversine_km(10.0, 20.0, 10.0, 20.0)), 0.0, places=6)

    def test_candidates(self):
        st_lat = [40.0, 40.0, 40.0, 40.0, 41.0]
        st_lon = [-100.3, -100.1, -100.5, -101.0, -100.0]
        # 0.1 deg of longitude at 40N is about 8.5 km: distances about 25.6, 8.5,
        # 42.6, 85.2 and 111.2 km.
        self.assertEqual(c.station_candidates(40.0, -100.0, st_lat, st_lon), [1, 0, 2])
        self.assertEqual(c.station_candidates(40.0, -100.0, st_lat, st_lon, km=30.0), [1, 0])
        self.assertEqual(c.station_candidates(None, -100.0, st_lat, st_lon), [])


class TestWeeksEvents(unittest.TestCase):
    def test_week(self):
        h0 = c.ehour(c.EPOCH0)
        self.assertEqual(c.week_index([h0, h0 + 167, h0 + 168, h0 - 1]).tolist(), [0, 0, 1, -1])

    def test_event_mask(self):
        a = c.ehour(c.d(2021, 2, 8))
        b = c.ehour(c.d(2021, 2, 21))
        self.assertEqual(c.event_mask([a - 1, a, b - 1, b]).tolist(), [False, True, True, False])
        self.assertEqual(len(c.EVENT_WINDOWS), 7)


class TestCountsRatio(unittest.TestCase):
    def test_counts(self):
        k = c.Counts(3)
        risk = np.array([True, True, True, False, True])
        trip = np.array([False, True, False, False, True])
        tb = np.array([0, 0, 7, 0, -1])
        wk = np.array([0, 1, 2, 0, 0])
        k.add("GAS_CC", risk, trip, tb, wk)
        r, t = k.pooled(c.GAS_CLASSES)
        self.assertEqual(int(r.sum()), 3)
        self.assertEqual(int(t.sum()), 1)
        self.assertEqual(int(r[0, 0]), 1)
        self.assertEqual(int(t[0, 1]), 1)
        self.assertEqual(int(r[7, 2]), 1)
        k.add("COAL", risk, trip, tb, wk, keep=np.array([False, True, True, True, True]))
        r, t = k.pooled(("COAL",))
        self.assertEqual(int(r.sum()), 2)
        self.assertEqual(int(t.sum()), 1)

    def test_ratio_and_ci(self):
        risk = np.zeros((c.N_BINS, 4), dtype=np.int64)
        trip = np.zeros((c.N_BINS, 4), dtype=np.int64)
        risk[0, :] = 5000
        trip[0, :] = 30
        risk[7, :] = 100000
        trip[7, :] = 100
        r = c.ratio(risk, trip, c.COLD, c.REF)
        # cold 120/20000 = 0.006, ref 400/400000 = 0.001 -> 6
        self.assertAlmostEqual(r["ratio"], 6.0)
        self.assertTrue(r["ok"])
        lo, hi = c.ratio_ci(risk, trip, c.COLD, c.REF, reps=50)
        self.assertAlmostEqual(lo, 6.0)
        self.assertAlmostEqual(hi, 6.0)
        trip[0, :] = 5
        self.assertFalse(c.ratio(risk, trip, c.COLD, c.REF)["ok"])
        self.assertIsNone(c.ratio(risk * 0, trip * 0, c.COLD, c.REF)["ratio"])


class TestScore(unittest.TestCase):
    def r(self, x, ok=True):
        return {"ratio": x, "ok": ok}

    def test_all(self):
        res = {"gas_cold": self.r(4.0), "coal_cold": self.r(1.2), "gas_cold_noevents": self.r(2.5),
               "gas_cold_placebo": self.r(2.0), "gas_hot": self.r(1.3), "gas_near_freeze": self.r(1.2),
               "gas_very_cold": self.r(5.0)}
        self.assertEqual(c.score(res), {"H1": True, "H2": False, "H3": True, "H4": True, "H5": True,
                                        "H6": True, "H7": True})

    def test_fail_and_missing(self):
        res = {"gas_cold": self.r(2.0), "coal_cold": self.r(2.5, ok=False), "gas_cold_placebo": self.r(1.5),
               "gas_hot": self.r(0.9), "gas_near_freeze": self.r(1.6), "gas_very_cold": self.r(3.5)}
        self.assertEqual(c.score(res), {"H1": False, "H2": None, "H3": None, "H4": None, "H5": False,
                                        "H6": False, "H7": False})


if __name__ == "__main__":
    unittest.main(verbosity=2)
