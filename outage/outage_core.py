# SPDX-License-Identifier: Apache-2.0
"""outage-1 core: find fossil-unit trips in public hourly gross-load data and
score them against official FERC/NERC cold-weather outage totals.

Pure Python (standard library only) so it can be tested anywhere. The plan,
with every definition and prediction, is docs/outage-plan.md
(Pre-registration id: outage-1).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's
name. Apache-2.0.
"""
import datetime as dt

UTC = dt.timezone.utc
HOUR = dt.timedelta(hours=1)

LOOKBACK_DAYS = 30      # hours read before each window (capability and run-up)
TAIL_HOURS = 6          # hours read after each window, to confirm late trips
MIN_CAP_MW = 25.0       # units below this capability are ignored
RUN_FRAC = 0.6          # "running hard": at least 60% of capability
OFF_FRAC = 0.02         # "off": at most 2% of capability
BACK_FRAC = 0.3         # a trip ends when output is back to 30% of capability
OFF_HOURS = 6           # hours the unit must stay off to count as a trip
CAP_PCT = 95            # capability = 95th percentile of positive hours ...
CAP_MIN_HOURS = 20      # ... when there are at least 20 of them, else the max

COAL = frozenset({"BIT", "SUB", "LIG", "RC", "WC", "ANT", "SGC"})
GAS = frozenset({"NG"})
OIL = frozenset({"DFO", "RFO", "JF", "KER", "WO"})

WEST_BAS = frozenset({
    "AVA", "AVRN", "AZPS", "BANC", "BPAT", "CHPD", "CISO", "DEAA", "DOPD", "EPE", "GCPD", "GRID",
    "GRIF", "GRMA", "GWA", "HGMA", "IID", "IPCO", "LDWP", "NEVP", "NWMT", "PACE", "PACW", "PGE",
    "PNM", "PSCO", "PSEI", "SCL", "SRP", "TEPC", "TIDC", "TPWR", "WACM", "WALC", "WAUW", "WWA"})
WEST_STATES = frozenset({"WA", "OR", "CA", "NV", "ID", "UT", "AZ", "CO", "WY", "MT", "NM"})
MISO_SOUTH_STATES = frozenset({"AR", "LA", "MS", "TX"})
SE_RC_BAS = frozenset({"SOCO", "AEC"})
AREAS = ("SW2011", "EAST_TX", "SC2018", "URI", "EAST", "EAST_TX_NOSE", "ERCOT")


def d(y, m, day):
    return dt.datetime(y, m, day, tzinfo=UTC)


# Official peak "incremental unplanned outages" (MW, all fuels, coincident).
# 2011-2022: FERC-NERC Winter Storm Elliott presentation, 21 Sep 2023.
# 2025: FERC-NERC "January 2025 Arctic Events" (Apr 2025), peak 22 Jan 2025.
# 2026: FERC-NERC "Arctic Events: Winter 2026" (Sep 2026), peak 26 Jan 2026.
EVENTS = [
    {"id": "E2011", "name": "2011 Southwest cold weather event", "start": d(2011, 2, 1),
     "end": d(2011, 2, 6), "area": "SW2011", "official_mw": 29700.0},
    {"id": "E2014", "name": "2014 Polar Vortex", "start": d(2014, 1, 5),
     "end": d(2014, 1, 9), "area": "EAST_TX", "official_mw": 19500.0},
    {"id": "E2018", "name": "2018 South Central cold weather event", "start": d(2018, 1, 15),
     "end": d(2018, 1, 18), "area": "SC2018", "official_mw": 15800.0},
    {"id": "E2021", "name": "2021 Winter Storm Uri", "start": d(2021, 2, 8),
     "end": d(2021, 2, 21), "area": "URI", "official_mw": 61300.0},
    {"id": "E2022", "name": "2022 Winter Storm Elliott", "start": d(2022, 12, 21),
     "end": d(2022, 12, 27), "area": "EAST", "official_mw": 90500.0},
    {"id": "E2025", "name": "January 2025 Arctic events", "start": d(2025, 1, 3),
     "end": d(2025, 1, 25), "area": "EAST_TX_NOSE", "official_mw": 71022.0},
    {"id": "E2026", "name": "Winter 2026 (Fern and Gianna)", "start": d(2026, 1, 22),
     "end": d(2026, 2, 3), "area": "EAST_TX_NOSE", "official_mw": 68169.0},
]
CONTROL_SHIFT_DAYS = (-364, 364, -728, -1092, 728)
N_CONTROLS = 2


def interconnection(ba, state):
    """'E' (Eastern), 'W' (Western), 'TX' (ERCOT) or None (AK/HI/PR/unknown)."""
    if ba == "ERCO":
        return "TX"
    if ba:
        return "W" if ba in WEST_BAS else "E"
    if not state or state in ("AK", "HI", "PR"):
        return None
    if state in WEST_STATES:
        return "W"
    if state == "TX":
        return "TX"
    return "E"


def in_area(area, ba, state):
    ic = interconnection(ba, state)
    if area == "SW2011":
        return ic == "TX" or state in ("AZ", "NM")
    if area == "EAST_TX":
        return ic in ("E", "TX")
    if area == "SC2018":
        return ba in ("SWPP", "TVA", "SOCO", "AEC") or (ba == "MISO" and state in MISO_SOUTH_STATES)
    if area == "URI":
        return ic == "TX" or ba == "SWPP" or (ba == "MISO" and state in MISO_SOUTH_STATES)
    if area == "EAST":
        return ic == "E"
    if area == "EAST_TX_NOSE":
        return ic in ("E", "TX") and ba not in SE_RC_BAS
    if area == "ERCOT":
        return ic == "TX"
    raise ValueError(area)


def ba_for_year(rows, year):
    """rows: (report_year, ba). Latest non-empty BA at or before year, else
    the earliest non-empty one after it, else None."""
    prior = [(y, b) for y, b in rows if b and y <= year]
    if prior:
        return max(prior)[1]
    later = [(y, b) for y, b in rows if b and y > year]
    if later:
        return min(later)[1]
    return None


def overlaps(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def control_windows(event, events, coverage_end):
    """First N_CONTROLS shifted copies of the event window that overlap no
    event window and end (with the tail) inside CEMS coverage."""
    out = []
    for s in CONTROL_SHIFT_DAYS:
        a0 = event["start"] + dt.timedelta(days=s)
        a1 = event["end"] + dt.timedelta(days=s)
        if a1 + TAIL_HOURS * HOUR > coverage_end:
            continue
        if any(overlaps(a0, a1, e["start"], e["end"]) for e in events):
            continue
        out.append((a0, a1))
        if len(out) == N_CONTROLS:
            break
    return out


def unit_cap(loads, end):
    """Capability from positive hours in loads[:end]."""
    pos = sorted(v for v in loads[:end] if v is not None and v > 0)
    if not pos:
        return 0.0
    if len(pos) < CAP_MIN_HOURS:
        return float(pos[-1])
    k = (CAP_PCT * len(pos) + 99) // 100  # nearest rank, 1-based
    return float(pos[k - 1])


def detect(loads, ws, we, cap, run_frac=RUN_FRAC, off_frac=OFF_FRAC, off_hours=OFF_HOURS,
           back_frac=BACK_FRAC):
    """Trips starting at hours ws..we-1 and the MW each hour of the window
    lost to them. A trip starts at hour i when the unit ran at >= run_frac*cap
    in hours i-3 and i-2 (hour i-1 is the transition hour, any value) and is
    at <= off_frac*cap in each of hours i..i+off_hours-1. It lasts until the
    first later hour at >= back_frac*cap. Returns (trips, contrib), trips as
    (start, end) with end None when the unit never came back in the data."""
    n = len(loads)
    contrib = [0.0] * (we - ws)
    trips = []
    if cap < MIN_CAP_MW:
        return trips, contrib
    run, off, back = run_frac * cap, off_frac * cap, back_frac * cap
    i = max(ws, 3)
    while i < we:
        if (loads[i - 3] >= run and loads[i - 2] >= run and i + off_hours <= n
                and all(loads[k] <= off for k in range(i, i + off_hours))):
            j = i + off_hours
            while j < n and loads[j] < back:
                j += 1
            trips.append((i, j if j < n else None))
            for k in range(i, min(j, we)):
                contrib[k - ws] += max(0.0, cap - loads[k])
            i = j
            continue
        i += 1
    return trips, contrib


def ran_hard(loads, lo, hi, cap, run_frac=RUN_FRAC):
    """True if the unit ran at >= run_frac*cap in two consecutive hours of [lo, hi)."""
    if cap < MIN_CAP_MW:
        return False
    run = run_frac * cap
    for k in range(max(lo, 1), hi):
        if loads[k - 1] >= run and loads[k] >= run:
            return True
    return False


def peak(series):
    """(max value, first index of it); (0.0, None) for an empty or all-zero series."""
    best, at = 0.0, None
    for i, v in enumerate(series):
        if v > best:
            best, at = v, i
    return best, at


def fuel_class(caps_by_esc):
    tot = {}
    for esc, mw in caps_by_esc.items():
        c = "COAL" if esc in COAL else "GAS" if esc in GAS else "OIL" if esc in OIL else "OTHER"
        tot[c] = tot.get(c, 0.0) + (mw or 0.0)
    if not tot:
        return "UNKNOWN"
    best = max(tot.values())
    top = [c for c, v in tot.items() if v == best]
    return top[0] if len(top) == 1 else "OTHER"


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return r


def spearman(xs, ys):
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def score(ev):
    """ev: event id -> {"T": peak MW or None, "controls": [peak MW, ...],
    "official": MW, "ercot_T": MW or None, "rate": {"GAS": x, "COAL": y}}.
    Returns P1..P5 as True (held), False (failed) or None (not scorable)."""
    ok = [k for k in sorted(ev) if ev[k].get("T") is not None and ev[k].get("official")]
    p = {}
    if len(ok) >= 5:
        p["P1"] = spearman([ev[k]["T"] for k in ok], [ev[k]["official"] for k in ok]) >= 0.70
    else:
        p["P1"] = None
    c = [k for k in ok if ev[k].get("controls")]
    if len(c) >= 5:
        misses = sum(1 for k in c if ev[k]["T"] <= max(ev[k]["controls"]))
        p["P2"] = misses <= 1
    else:
        p["P2"] = None
    if len(ok) >= 5:
        m = median([ev[k]["T"] / ev[k]["official"] for k in ok])
        p["P3"] = 0.10 <= m <= 0.60
    else:
        p["P3"] = None
    a, b = ev.get("E2026", {}).get("ercot_T"), ev.get("E2025", {}).get("ercot_T")
    p["P4"] = None if a is None or b is None else a > b
    vals = []
    for k in ("E2022", "E2026"):
        r = ev.get(k, {}).get("rate") or {}
        vals.append((r.get("GAS"), r.get("COAL")))
    if all(g is not None and co is not None for g, co in vals):
        p["P5"] = all(g > co for g, co in vals)
    else:
        p["P5"] = None
    return p
