# SPDX-License-Identifier: Apache-2.0
"""Hand-checked tests for repeat_core (repeat-1). MV2 of Munim, Inc. Made with
AI agents working in MV2's name. Apache-2.0."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repeat_core as r  # noqa: E402


def rows_two_strata():
    """Stratum AA: 4 tripped in A (2 trip again in B); 6 did not (1 trips in B).
    Stratum BB: 1 tripped in A (trips again); 9 did not (2 trip in B)."""
    fa, fb = {}, {}
    for i in range(4):
        fa["a%d" % i] = (1, "AA", True)
        fb["a%d" % i] = (1, "AA", i < 2)
    for i in range(6):
        fa["b%d" % i] = (2, "AA", False)
        fb["b%d" % i] = (2, "AA", i < 1)
    fa["c0"] = (3, "BB", True)
    fb["c0"] = (3, "BB", True)
    for i in range(9):
        fa["d%d" % i] = (4, "BB", False)
        fb["d%d" % i] = (4, "BB", i < 2)
    return r.pair_rows(fa, fb)


class TestRepeatCore(unittest.TestCase):
    def test_pair_rows_keeps_units_eligible_in_both(self):
        fa = {"x": (1, "TX", True), "y": (1, "TX", False), "z": (2, "", True)}
        fb = {"x": (1, "TX", False), "z": (2, "OK", True), "w": (3, "LA", True)}
        self.assertEqual(r.pair_rows(fa, fb), [("x", 1, "TX", True, False), ("z", 2, "??", True, True)])

    def test_strata_counts(self):
        c = r.strata(rows_two_strata(), "P")
        self.assertEqual(c[("P", "AA")], [2, 4, 1, 6])
        self.assertEqual(c[("P", "BB")], [1, 1, 2, 9])
        self.assertEqual(r.totals(c), {"a": 3, "n1": 5, "c": 3, "n0": 15})

    def test_mh_rr_by_hand(self):
        # AA: N=10, a*n0/N = 2*6/10 = 1.2, c*n1/N = 1*4/10 = 0.4
        # BB: N=10, a*n0/N = 1*9/10 = 0.9, c*n1/N = 2*1/10 = 0.2
        # MH = 2.1 / 0.6 = 3.5
        c = r.strata(rows_two_strata())
        self.assertAlmostEqual(r.mh_rr(c), 3.5, places=9)

    def test_crude_by_hand(self):
        t = r.crude(r.strata(rows_two_strata()))
        self.assertAlmostEqual(t["risk_if_tripped_in_A"], 0.6)
        self.assertAlmostEqual(t["risk_if_not"], 0.2)
        self.assertAlmostEqual(t["crude_rr"], 3.0)

    def test_mh_rr_edges(self):
        self.assertIsNone(r.mh_rr({}))
        self.assertIsNone(r.mh_rr({"k": [0, 1, 0, 5]}))
        self.assertEqual(r.mh_rr({"k": [1, 1, 0, 5]}), math.inf)
        self.assertIsNone(r.mh_rr({"k": [0, 0, 0, 0]}))

    def test_scorable(self):
        self.assertFalse(r.scorable(r.strata(rows_two_strata())))   # n1 = 5
        self.assertTrue(r.scorable({"k": [5, 10, 5, 10]}))
        self.assertFalse(r.scorable({"k": [5, 10, 4, 10]}))          # 9 trips in B
        self.assertFalse(r.scorable({"k": [5, 9, 5, 10]}))           # n1 = 9

    def test_pct(self):
        v = [5, 1, 3, 2, 4]
        self.assertEqual(r.pct(v, 50), 3)
        self.assertEqual(r.pct(v, 95), 5)
        self.assertEqual(r.pct(v, 2.5), 1)
        self.assertEqual(r.pct(v, 0), 1)
        self.assertIsNone(r.pct([], 50))
        self.assertEqual(r.pct(list(range(100)), 95), 94)

    def test_boot_identical_plants_gives_constant(self):
        # one stratum a=1, n1=2, c=1, n0=4: (1*4/6)/(1*2/6) = 2.0, and any
        # resample of two identical plants scales all counts, keeping 2.0
        pc = {1: {("P", ("t", "S")): [1, 2, 1, 4]}, 2: {("P", ("t", "S")): [1, 2, 1, 4]}}
        reps = r.boot(pc, ["P"], reps=25, seed=1)
        self.assertEqual(len(reps), 25)
        for x in reps:
            self.assertAlmostEqual(x["P"], 2.0)
        lo, hi, n_none = r.ci95(reps, "P")
        self.assertAlmostEqual(lo, 2.0)
        self.assertAlmostEqual(hi, 2.0)
        self.assertEqual(n_none, 0)
        self.assertEqual(r.boot({}, ["P"]), [])

    def test_repeaters(self):
        f = {"E1": {"u1": (1, "S", True), "u2": (1, "S", True), "u3": (2, "S", False)},
             "E2": {"u1": (1, "S", True), "u2": (1, "S", True), "u3": (2, "S", True)},
             "E3": {"u1": (1, "S", True), "u2": (1, "S", False), "u3": (2, "S", True)},
             "E4": {"u3": (2, "S", True)}}
        self.assertEqual(r.repeaters(f), ["u1", "u3"])

    def test_perm_null_extremes(self):
        all_trip = {e: {"u1": (1, "S", True), "u2": (2, "S", True)} for e in ("E1", "E2", "E3")}
        self.assertEqual(set(r.perm_null(all_trip, reps=50)), {2})
        none = {e: {"u1": (1, "S", False), "u2": (2, "S", False)} for e in ("E1", "E2", "E3")}
        self.assertEqual(set(r.perm_null(none, reps=50)), {0})

    def test_perm_null_mean(self):
        # 4 units, 3 events, one trip per event dealt at random: the chance
        # that one unit gets all 3 is 4 * (1/4)^3 = 1/16 = 0.0625
        f = {e: {"u%d" % i: (i, "S", i == 0) for i in range(4)} for e in ("E1", "E2", "E3")}
        null = r.perm_null(f, reps=4000, seed=7)
        mean = sum(null) / len(null)
        self.assertTrue(0.045 <= mean <= 0.08, mean)
        self.assertEqual(set(null) - {0, 1}, set())

    def test_perm_null_keeps_states_apart(self):
        # the trip in state A can never land on the unit in state B
        f = {e: {"a": (1, "A", True), "b": (2, "B", False)} for e in ("E1", "E2", "E3")}
        self.assertEqual(set(r.perm_null(f, reps=30)), {1})

    def test_score(self):
        pr = {"E2022>E2026": (2.5, True), "E2021>E2022": (1.5, True)}
        pools = {"PRE": 2.0, "POST": 1.5, "EVENT": 1.8, "PLACEBO": 1.2}
        s = r.score(pr, pools, 10, list(range(100)))
        self.assertEqual(s, {"R1": True, "R2": False, "R3": True, "R4": True, "R5": False})
        s = r.score({"E2022>E2026": (2.0, True)}, {}, 95, list(range(100)))
        self.assertEqual(s, {"R1": True, "R2": None, "R3": None, "R4": None, "R5": True})
        s = r.score({"E2022>E2026": (5.0, False)}, {"PRE": 1.0}, None, [])
        self.assertEqual(s, {"R1": None, "R2": None, "R3": None, "R4": None, "R5": None})

    def test_pairs_fixed(self):
        self.assertEqual(r.pair_name(r.R1_PAIR), "E2022>E2026")
        self.assertEqual(r.pair_name(r.R2_PAIR), "E2021>E2022")
        self.assertEqual(len(r.ALL_PAIRS), 6)
        self.assertIn(r.R1_PAIR, r.POST_PAIRS)
        self.assertIn(r.R2_PAIR, r.PRE_PAIRS)


if __name__ == "__main__":
    unittest.main()
