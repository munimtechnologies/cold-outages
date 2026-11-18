# SPDX-License-Identifier: Apache-2.0
"""repeat-1 core: do the same fossil units fail storm after storm, and did
that change after NERC's cold-weather standard EOP-012 took effect
(1 October 2024)?

Pure Python (standard library only) so it can be tested anywhere. Trips and
"ran hard" come from the pre-registered outage-1 rule (outage/outage_core.py,
unchanged). The plan, with every definition and prediction, is
docs/repeat-plan.md (Pre-registration id: repeat-1).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's
name. Apache-2.0.
"""
import math
import random

AREA = "EAST_TX"            # outage-1 area: Eastern Interconnection + ERCOT
RR_BAR = 2.0                # R1, R2: repeat risk ratio at least this
MIN_N1 = 10                 # a pair is scorable with >= 10 units that tripped in A ...
MIN_BTRIPS = 10             # ... and >= 10 units that tripped in B (both eligible in A and B)
MIN_EVENTS_REPEATER = 3     # a "repeater" tripped in at least 3 cold events
N_BOOT = 1000               # plant-cluster bootstrap replicates
N_PERM = 1000               # permutations for R5
SEED = 20261118

PRE_PAIRS = (("E2014", "E2018"), ("E2018", "E2021"), ("E2021", "E2022"))
POST_PAIRS = (("E2022", "E2025"), ("E2022", "E2026"), ("E2025", "E2026"))
ALL_PAIRS = PRE_PAIRS + POST_PAIRS
R1_PAIR = ("E2022", "E2026")
R2_PAIR = ("E2021", "E2022")


def pair_name(pair):
    return "%s>%s" % pair


def pair_rows(fa, fb):
    """fa, fb: unit key -> (plant, state, tripped) for the units eligible
    (ran hard) in windows A and B. Returns, for units eligible in both,
    sorted (unit, plant, state of A, tripped in A, tripped in B)."""
    out = []
    for u in sorted(set(fa) & set(fb)):
        plant, state, ta = fa[u]
        tb = fb[u][2]
        out.append((u, plant, state or "??", bool(ta), bool(tb)))
    return out


def add(counts, key, a_trip, b_trip, w=1):
    """counts[key] = [a, n1, c, n0]: n1 units tripped in A, a of them also
    tripped in B; n0 units did not trip in A, c of them tripped in B."""
    v = counts.setdefault(key, [0, 0, 0, 0])
    if a_trip:
        v[1] += w
        if b_trip:
            v[0] += w
    else:
        v[3] += w
        if b_trip:
            v[2] += w
    return counts


def strata(rows, tag=None):
    """Counts stratified by the state of each unit (key (tag, state))."""
    counts = {}
    for _u, _p, s, ta, tb in rows:
        add(counts, (tag, s), ta, tb)
    return counts


def totals(counts):
    a = sum(v[0] for v in counts.values())
    n1 = sum(v[1] for v in counts.values())
    c = sum(v[2] for v in counts.values())
    n0 = sum(v[3] for v in counts.values())
    return {"a": a, "n1": n1, "c": c, "n0": n0}


def mh_rr(counts):
    """Mantel-Haenszel risk ratio over strata: sum(a*n0/N) / sum(c*n1/N).
    None when both sums are 0, inf when only the denominator is 0."""
    num = den = 0.0
    for a, n1, c, n0 in counts.values():
        n = n1 + n0
        if n == 0:
            continue
        num += a * n0 / n
        den += c * n1 / n
    if den == 0:
        return None if num == 0 else math.inf
    return num / den


def crude(counts):
    t = totals(counts)
    r1 = t["a"] / t["n1"] if t["n1"] else None
    r0 = t["c"] / t["n0"] if t["n0"] else None
    rr = None
    if r1 is not None and r0:
        rr = r1 / r0
    elif r1 and r0 == 0:
        rr = math.inf
    t.update({"risk_if_tripped_in_A": r1, "risk_if_not": r0, "crude_rr": rr})
    return t


def scorable(counts):
    t = totals(counts)
    return t["n1"] >= MIN_N1 and t["a"] + t["c"] >= MIN_BTRIPS


def pct(vals, q):
    """Nearest-rank percentile (q in 0..100) of a list; None if empty."""
    s = sorted(vals)
    if not s:
        return None
    k = max(1, int(math.ceil(q / 100.0 * len(s))))
    return s[k - 1]


def boot(plant_counts, pools, reps=N_BOOT, seed=SEED):
    """Plant-cluster bootstrap. plant_counts: plant -> {(pool, stratum):
    [a, n1, c, n0]}. Each replicate draws as many plants as there are, with
    replacement, and recomputes the MH risk ratio of each pool. Returns a
    list (one dict pool -> RR or None per replicate)."""
    rng = random.Random(seed)
    plants = sorted(plant_counts)
    out = []
    if not plants:
        return out
    for _ in range(reps):
        counts = {p: {} for p in pools}
        for _k in range(len(plants)):
            pc = plant_counts[plants[rng.randrange(len(plants))]]
            for (pool, st), v in pc.items():
                if pool not in counts:
                    continue
                cur = counts[pool].setdefault(st, [0, 0, 0, 0])
                for i in range(4):
                    cur[i] += v[i]
        out.append({p: mh_rr(counts[p]) for p in pools})
    return out


def ci95(reps, pool):
    vals = [r[pool] for r in reps if r.get(pool) is not None]
    return (pct(vals, 2.5), pct(vals, 97.5), len(reps) - len(vals))


def repeaters(flags_by_event, min_events=MIN_EVENTS_REPEATER):
    """Units that tripped in at least min_events of the events.
    flags_by_event: event id -> unit key -> (plant, state, tripped)."""
    n = {}
    for ev in sorted(flags_by_event):
        for u, (_p, _s, t) in flags_by_event[ev].items():
            if t:
                n[u] = n.get(u, 0) + 1
    return sorted(u for u, k in n.items() if k >= min_events)


def perm_null(flags_by_event, reps=N_PERM, seed=SEED, min_events=MIN_EVENTS_REPEATER):
    """Null distribution of the number of repeaters: within each event and
    state, the trips are dealt at random among the eligible units (the
    number of trips per event and state is kept)."""
    rng = random.Random(seed)
    groups = []
    for ev in sorted(flags_by_event):
        by = {}
        for u in sorted(flags_by_event[ev]):
            _p, s, t = flags_by_event[ev][u]
            g = by.setdefault(s or "??", [[], 0])
            g[0].append(u)
            if t:
                g[1] += 1
        for s in sorted(by):
            if by[s][1]:
                groups.append(by[s])
    out = []
    for _ in range(reps):
        n = {}
        for units, k in groups:
            for u in rng.sample(units, k):
                n[u] = n.get(u, 0) + 1
        out.append(sum(1 for v in n.values() if v >= min_events))
    return out


def score(pair_rr, pool_rr, rep_obs, rep_null):
    """pair_rr: pair name -> (MH RR or None, scorable bool).
    pool_rr: "PRE", "POST", "EVENT", "PLACEBO" -> MH RR or None (None also
    when the pool holds no scorable pair). rep_obs: observed repeaters (int
    or None); rep_null: list of null counts. Returns R1..R5 as True (held),
    False (failed) or None (not scorable)."""
    p = {}
    for name, pair in (("R1", R1_PAIR), ("R2", R2_PAIR)):
        rr, ok = pair_rr.get(pair_name(pair), (None, False))
        p[name] = (rr >= RR_BAR) if (ok and rr is not None) else None
    pre, post = pool_rr.get("PRE"), pool_rr.get("POST")
    p["R3"] = (post < pre) if (pre is not None and post is not None) else None
    ev, pl = pool_rr.get("EVENT"), pool_rr.get("PLACEBO")
    p["R4"] = (ev > pl) if (ev is not None and pl is not None) else None
    if rep_obs is None or not rep_null:
        p["R5"] = None
    else:
        p["R5"] = rep_obs > pct(rep_null, 95)
    return p
