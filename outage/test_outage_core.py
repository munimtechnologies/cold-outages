# SPDX-License-Identifier: Apache-2.0
"""Tests for outage_core. Every expected value was worked out by hand.
MV2 of Munim, Inc. Made with AI agents working in MV2's name. Apache-2.0."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outage_core as c  # noqa: E402

d = c.d


class TestDetect(unittest.TestCase):
    SERIES = [80, 80, 80, 90, 40, 0, 0, 0, 0, 0, 0, 10, 50, 80, 80, 0, 0, 0, 0, 0]

    def test_trip_with_transition_hour(self):
        trips, contrib = c.detect(self.SERIES, 3, 14, 100.0)
        self.assertEqual(trips, [(5, 12)])
        self.assertEqual(contrib, [0, 0, 100, 100, 100, 100, 100, 100, 90, 0, 0])
        self.assertEqual(c.peak(contrib), (100.0, 2))

    def test_late_trip_not_confirmable(self):
        trips, contrib = c.detect(self.SERIES, 3, 17, 100.0)
        self.assertEqual(trips, [(5, 12)])
        self.assertEqual(contrib, [0, 0, 100, 100, 100, 100, 100, 100, 90, 0, 0, 0, 0, 0])

    def test_unrecovered_trip(self):
        loads = [80, 80, 80, 0, 0, 0, 0, 0, 0, 0]
        cap = c.unit_cap(loads, 10)
        self.assertEqual(cap, 80.0)
        trips, contrib = c.detect(loads, 0, 10, cap)
        self.assertEqual(trips, [(3, None)])
        self.assertEqual(contrib, [0, 0, 0, 80, 80, 80, 80, 80, 80, 80])

    def test_slow_ramp_is_not_a_trip(self):
        trips, contrib = c.detect([80, 80, 50, 30, 0, 0, 0, 0, 0, 0], 0, 10, 100.0)
        self.assertEqual(trips, [])
        self.assertEqual(contrib, [0.0] * 10)

    def test_small_unit_ignored(self):
        trips, contrib = c.detect(self.SERIES, 3, 14, 20.0)
        self.assertEqual(trips, [])
        self.assertEqual(contrib, [0.0] * 11)

    def test_off_hours_variant(self):
        loads = [80, 80, 80, 0, 0, 0, 0, 50, 80, 80]
        self.assertEqual(c.detect(loads, 0, 7, 100.0)[0], [])
        trips, contrib = c.detect(loads, 0, 7, 100.0, off_hours=4)
        self.assertEqual(trips, [(3, 7)])
        self.assertEqual(contrib, [0, 0, 0, 100, 100, 100, 100])


class TestHelpers(unittest.TestCase):
    def test_unit_cap(self):
        self.assertEqual(c.unit_cap(list(range(1, 21)), 20), 19.0)
        self.assertEqual(c.unit_cap(list(range(1, 22)), 21), 20.0)
        self.assertEqual(c.unit_cap([0, None, 5, 3], 4), 5.0)
        self.assertEqual(c.unit_cap([0, 0], 2), 0.0)
        self.assertEqual(c.unit_cap([5, 100], 1), 5.0)

    def test_ran_hard(self):
        self.assertTrue(c.ran_hard([0, 70, 70, 0], 0, 4, 100.0))
        self.assertFalse(c.ran_hard([0, 70, 0, 70], 0, 4, 100.0))
        self.assertFalse(c.ran_hard([0, 70, 70, 0], 0, 4, 20.0))

    def test_peak(self):
        self.assertEqual(c.peak([]), (0.0, None))
        self.assertEqual(c.peak([0, 0]), (0.0, None))
        self.assertEqual(c.peak([1, 3, 3, 2]), (3, 1))

    def test_fuel_class(self):
        self.assertEqual(c.fuel_class({"NG": 100, "BIT": 50}), "GAS")
        self.assertEqual(c.fuel_class({"SUB": 10}), "COAL")
        self.assertEqual(c.fuel_class({}), "UNKNOWN")
        self.assertEqual(c.fuel_class({"NG": 50, "BIT": 50}), "OTHER")
        self.assertEqual(c.fuel_class({"DFO": 30, "WND": 10}), "OIL")

    def test_ranks_spearman_median(self):
        self.assertEqual(c.ranks([5, 5, 1]), [2.5, 2.5, 1.0])
        self.assertAlmostEqual(c.spearman([1, 2, 3, 4], [10, 20, 40, 30]), 0.8)
        self.assertIsNone(c.spearman([1, 2], [1, 2]))
        self.assertIsNone(c.spearman([1, 1, 1], [1, 2, 3]))
        self.assertEqual(c.median([3, 1, 2]), 2)
        self.assertEqual(c.median([4, 1, 2, 3]), 2.5)
        self.assertIsNone(c.median([]))


class TestAreas(unittest.TestCase):
    def test_interconnection(self):
        self.assertEqual(c.interconnection("ERCO", "TX"), "TX")
        self.assertEqual(c.interconnection("PNM", "NM"), "W")
        self.assertEqual(c.interconnection("PJM", "PA"), "E")
        self.assertEqual(c.interconnection("", "TX"), "TX")
        self.assertEqual(c.interconnection(None, "OR"), "W")
        self.assertIsNone(c.interconnection("", "HI"))
        self.assertEqual(c.interconnection("", "OH"), "E")

    def test_in_area(self):
        self.assertTrue(c.in_area("URI", "MISO", "LA"))
        self.assertFalse(c.in_area("URI", "MISO", "MN"))
        self.assertTrue(c.in_area("URI", "SWPP", "OK"))
        self.assertTrue(c.in_area("URI", "ERCO", "TX"))
        self.assertFalse(c.in_area("EAST_TX_NOSE", "SOCO", "GA"))
        self.assertTrue(c.in_area("EAST_TX_NOSE", "ERCO", "TX"))
        self.assertFalse(c.in_area("EAST", "ERCO", "TX"))
        self.assertTrue(c.in_area("EAST", "PJM", "PA"))
        self.assertTrue(c.in_area("SW2011", "", "NM"))
        self.assertFalse(c.in_area("SW2011", "PJM", "PA"))
        self.assertTrue(c.in_area("SC2018", "TVA", "TN"))
        self.assertFalse(c.in_area("SC2018", "MISO", "MI"))
        self.assertFalse(c.in_area("EAST", "", "OR"))
        self.assertTrue(c.in_area("ERCOT", "", "TX"))
        with self.assertRaises(ValueError):
            c.in_area("X", "PJM", "PA")

    def test_ba_for_year(self):
        rows = [(2013, "MISO"), (2020, "SWPP"), (2022, "")]
        self.assertEqual(c.ba_for_year(rows, 2021), "SWPP")
        self.assertEqual(c.ba_for_year(rows, 2011), "MISO")
        self.assertEqual(c.ba_for_year(rows, 2023), "SWPP")
        self.assertIsNone(c.ba_for_year([], 2020))


class TestEventsAndControls(unittest.TestCase):
    def test_events(self):
        self.assertEqual([e["id"] for e in c.EVENTS],
                         ["E2011", "E2014", "E2018", "E2021", "E2022", "E2025", "E2026"])
        for e in c.EVENTS:
            self.assertLess(e["start"], e["end"])
            self.assertIn(e["area"], c.AREAS)

    def by_id(self, k):
        return [e for e in c.EVENTS if e["id"] == k][0]

    def test_controls_2026(self):
        got = c.control_windows(self.by_id("E2026"), c.EVENTS, d(2026, 10, 1))
        self.assertEqual(got, [(d(2024, 1, 25), d(2024, 2, 6)), (d(2023, 1, 26), d(2023, 2, 7))])

    def test_controls_2025(self):
        got = c.control_windows(self.by_id("E2025"), c.EVENTS, d(2026, 10, 1))
        self.assertEqual(got, [(d(2024, 1, 5), d(2024, 1, 27)), (d(2023, 1, 6), d(2023, 1, 28))])

    def test_controls_2011(self):
        got = c.control_windows(self.by_id("E2011"), c.EVENTS, d(2026, 10, 1))
        self.assertEqual(got, [(d(2010, 2, 2), d(2010, 2, 7)), (d(2012, 1, 31), d(2012, 2, 5))])


class TestScore(unittest.TestCase):
    def make(self):
        ev = {}
        for e in c.EVENTS:
            t = e["official_mw"] * 0.3
            ev[e["id"]] = {"T": t, "controls": [0.1 * t, 0.05 * t], "official": e["official_mw"]}
        ev["E2026"]["ercot_T"] = 5000.0
        ev["E2025"]["ercot_T"] = 4000.0
        ev["E2022"]["rate"] = {"GAS": 0.1, "COAL": 0.05}
        ev["E2026"]["rate"] = {"GAS": 0.08, "COAL": 0.09}
        return ev

    def test_all(self):
        self.assertEqual(c.score(self.make()), {"P1": True, "P2": True, "P3": True, "P4": True, "P5": False})

    def test_controls_fail(self):
        ev = self.make()
        ev["E2011"]["controls"] = [ev["E2011"]["T"], 0.0]
        ev["E2014"]["controls"] = [ev["E2014"]["T"] * 2]
        self.assertFalse(c.score(ev)["P2"])
        ev["E2014"]["controls"] = [0.0]
        self.assertTrue(c.score(ev)["P2"])

    def test_not_scorable(self):
        ev = self.make()
        for k in ("E2011", "E2014", "E2018"):
            ev[k]["T"] = None
        del ev["E2026"]["ercot_T"]
        del ev["E2022"]["rate"]
        self.assertEqual(c.score(ev), {"P1": None, "P2": None, "P3": None, "P4": None, "P5": None})


if __name__ == "__main__":
    unittest.main(verbosity=2)
