# SPDX-License-Identifier: Apache-2.0
"""temp-1 core: hourly trip hazard of U.S. fossil units by local air
temperature, from EPA's public hourly emissions data (CEMS) and NOAA ISD-Lite.

numpy only, so it can be tested anywhere. The plan, with every definition and
prediction, is docs/temp-plan.md (Pre-registration id: temp-1).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's
name. Apache-2.0.
"""
import datetime as dt
import gzip
import math

import numpy as np

UTC = dt.timezone.utc

YEARS = tuple(range(2016, 2026))     # analysis years (temperature files end in 2025)
PLACEBO_SHIFT_H = 364 * 24           # placebo temperature: same plant, 364 days earlier
MIN_CAP_MW = 25.0
RUN_FRAC = 0.6                       # hours i-3 and i-2 at >= 60% of capability
OFF_FRAC = 0.02                      # off = at most 2% of capability
CAP_PCT = 95
CAP_MIN_HOURS = 20
STATION_KM = 50.0
STATION_CANDIDATES = 3
MIN_STATION_HOURS = 2000             # a station-year needs this many hours with a temperature
FILL_HOURS = 2                       # gaps up to 2 h are filled from the nearest observation

# Detection rules: the transition hour i-1 must be above prev_frac*cap, and
# hours i..i+off_hours-1 at or below OFF_FRAC*cap.
RULES = {
    "abrupt": {"prev_frac": 0.3, "off_hours": 6},    # primary
    "stage1": {"prev_frac": 0.02, "off_hours": 6},   # close to outage-1's rule
    "long": {"prev_frac": 0.3, "off_hours": 12},     # stays off half a day or more
}

EDGES = (-20, -15, -10, -5, 0, 5, 10, 15, 20, 25, 30, 35)   # deg C; 13 bins, 0..12
N_BINS = len(EDGES) + 1
COLD = (0, 1, 2)          # below -10 C
VERY_COLD = (0, 1)        # below -15 C
NEAR_FREEZE = (4,)        # -5 C to 0 C
REF = (7, 8)              # 10 C to 20 C
HOT = (12,)               # 35 C and above

COAL = frozenset({"BIT", "SUB", "LIG", "RC", "WC", "ANT", "SGC"})
GAS = frozenset({"NG"})
OIL = frozenset({"DFO", "RFO", "JF", "KER", "WO"})
CLASSES = ("COAL", "GAS_CC", "GAS_CT", "GAS_ST", "GAS_OTHER", "OIL", "OTHER")
GAS_CLASSES = ("GAS_CC", "GAS_CT", "GAS_ST", "GAS_OTHER")


def d(y, m, day):
    return dt.datetime(y, m, day, tzinfo=UTC)


# The seven cold-event windows of outage-1 (docs/outage-plan.md). Hours inside
# them are dropped for the "no named storms" check (H4).
EVENT_WINDOWS = (
    (d(2011, 2, 1), d(2011, 2, 6)), (d(2014, 1, 5), d(2014, 1, 9)), (d(2018, 1, 15), d(2018, 1, 18)),
    (d(2021, 2, 8), d(2021, 2, 21)), (d(2022, 12, 21), d(2022, 12, 27)), (d(2025, 1, 3), d(2025, 1, 25)),
    (d(2026, 1, 22), d(2026, 2, 3)),
)
EPOCH0 = d(2016, 1, 1)


def ehour(t):
    return int(t.timestamp()) // 3600


def year_hours(y):
    return (dt.date(y + 1, 1, 1) - dt.date(y, 1, 1)).days * 24


def week_index(epoch_hours):
    """Weeks since 2016-01-01 00:00 UTC (the bootstrap blocks)."""
    return (np.asarray(epoch_hours, dtype=np.int64) - ehour(EPOCH0)) // 168


def event_mask(epoch_hours):
    h = np.asarray(epoch_hours, dtype=np.int64)
    m = np.zeros(h.shape, dtype=bool)
    for a, b in EVENT_WINDOWS:
        m |= (h >= ehour(a)) & (h < ehour(b))
    return m


def unit_class(gens):
    """gens: list of (energy_source_code_1, prime_mover_code, capacity_mw) of
    the generators behind one EPA unit. Fuel by capacity (ties -> OTHER); a gas
    unit is then split by the prime mover with the most capacity."""
    tot = {}
    for esc, _pm, mw in gens:
        if not esc:
            continue
        c = "COAL" if esc in COAL else "GAS" if esc in GAS else "OIL" if esc in OIL else "OTHER"
        tot[c] = tot.get(c, 0.0) + (mw or 0.0)
    if not tot:
        return "OTHER"
    best = max(tot.values())
    top = [c for c, v in tot.items() if v == best]
    if len(top) != 1:
        return "OTHER"
    if top[0] != "GAS":
        return top[0]
    pms = {}
    for esc, pm, mw in gens:
        if esc in GAS and pm:
            pms[pm] = pms.get(pm, 0.0) + (mw or 0.0)
    if not pms:
        return "GAS_OTHER"
    pm = max(sorted(pms), key=lambda k: pms[k])
    if pm in ("CA", "CT", "CS", "CC"):
        return "GAS_CC"
    if pm == "GT":
        return "GAS_CT"
    if pm == "ST":
        return "GAS_ST"
    return "GAS_OTHER"


def cap_np(loads):
    """Capability: 95th percentile (nearest rank) of positive hours when there
    are at least 20, else the largest; 0 when none (same as outage-1)."""
    x = np.asarray(loads, dtype=np.float64)
    pos = np.sort(x[x > 0])
    if pos.size == 0:
        return 0.0
    if pos.size < CAP_MIN_HOURS:
        return float(pos[-1])
    k = (CAP_PCT * pos.size + 99) // 100
    return float(pos[k - 1])


def risk_trip(loads, cap, prev_frac, off_hours):
    """Boolean arrays (risk, trip), one entry per hour.
    risk[i]: hours i-3 and i-2 at >= RUN_FRAC*cap, hour i-1 above prev_frac*cap,
    and hours i..i+off_hours-1 inside the series.
    trip[i]: risk[i] and every hour i..i+off_hours-1 at <= OFF_FRAC*cap.
    A trip at i makes hour i+1 not at risk, so no trip is counted twice."""
    x = np.asarray(loads, dtype=np.float64)
    n = x.size
    risk = np.zeros(n, dtype=bool)
    trip = np.zeros(n, dtype=bool)
    if cap < MIN_CAP_MW or n < 3 + off_hours:
        return risk, trip
    run, off, prev = RUN_FRAC * cap, OFF_FRAC * cap, prev_frac * cap
    i = np.arange(3, n - off_hours + 1)
    r = (x[i - 3] >= run) & (x[i - 2] >= run) & (x[i - 1] > prev)
    mx = np.lib.stride_tricks.sliding_window_view(x, off_hours).max(axis=1)
    risk[i] = r
    trip[i] = r & (mx[i] <= off)
    return risk, trip


def temp_bin(t):
    """deg C -> bin 0..12 (see EDGES); NaN -> -1."""
    t = np.asarray(t, dtype=np.float64)
    b = np.digitize(np.where(np.isnan(t), 0.0, t), EDGES)
    return np.where(np.isnan(t), -1, b).astype(np.int64)


def parse_isd_lite(data, year):
    """ISD-Lite text (bytes or str, gzip allowed) -> float32 array of hourly air
    temperature (deg C, UTC) for the year; NaN where missing."""
    if isinstance(data, bytes):
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        data = data.decode("ascii", "replace")
    n = year_hours(year)
    out = np.full(n, np.nan, dtype=np.float32)
    jan1 = dt.date(year, 1, 1)
    for line in data.splitlines():
        f = line.split()
        if len(f) < 5:
            continue
        try:
            y, m, dd, hh, t = int(f[0]), int(f[1]), int(f[2]), int(f[3]), int(f[4])
        except ValueError:
            continue
        if y != year or t == -9999:
            continue
        try:
            k = (dt.date(y, m, dd) - jan1).days * 24 + hh
        except ValueError:
            continue
        if 0 <= k < n:
            out[k] = t / 10.0
    return out


def fill_gaps(t, max_gap=FILL_HOURS):
    """Fill a missing hour from the nearest observation within max_gap hours
    (the earlier one on a tie). Only original observations are used."""
    t = np.asarray(t, dtype=np.float32)
    out = t.copy()
    miss = np.isnan(t)
    n = t.size
    for off in range(1, max_gap + 1):
        for s in (-off, off):
            src = np.full(n, np.nan, dtype=np.float32)
            if s < 0:
                src[-s:] = t[:n + s]
            else:
                src[:n - s] = t[s:]
            take = np.isnan(out) & miss & ~np.isnan(src)
            out[take] = src[take]
    return out


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance (km, R = 6371); lat2/lon2 may be arrays."""
    p1, p2 = math.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(np.asarray(lon2, dtype=np.float64) - lon1)
    a = np.sin(dphi / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def station_candidates(lat, lon, st_lat, st_lon, km=STATION_KM, k=STATION_CANDIDATES):
    """Indices of up to k stations within km of (lat, lon), nearest first."""
    if lat is None or lon is None or len(st_lat) == 0:
        return []
    dist = haversine_km(lat, lon, np.asarray(st_lat, dtype=np.float64), np.asarray(st_lon, dtype=np.float64))
    idx = np.nonzero(dist <= km)[0]
    order = idx[np.argsort(dist[idx], kind="stable")]
    return [int(j) for j in order[:k]]


def shifted_temp(prev, cur, shift):
    """Temperature `shift` hours earlier for every hour of the current year,
    using the previous year's series (NaN when not available)."""
    cur = np.asarray(cur, dtype=np.float32)
    if prev is None:
        prev = np.full(0, np.nan, dtype=np.float32)
    both = np.concatenate([np.asarray(prev, dtype=np.float32), cur])
    k = np.arange(cur.size) + len(prev) - shift
    out = np.full(cur.size, np.nan, dtype=np.float32)
    ok = k >= 0
    out[ok] = both[k[ok]]
    return out


class Counts:
    """At-risk unit-hours and trips by class, temperature bin and week."""

    def __init__(self, n_weeks):
        self.n_weeks = n_weeks
        self.risk = np.zeros((len(CLASSES), N_BINS, n_weeks), dtype=np.int64)
        self.trip = np.zeros((len(CLASSES), N_BINS, n_weeks), dtype=np.int64)

    def add(self, cls, risk, trip, tbin, week, keep=None):
        """risk/trip: boolean per hour; tbin: temperature bin per hour (-1 =
        none); week: week per hour; keep: optional extra boolean mask."""
        c = CLASSES.index(cls)
        ok = risk & (tbin >= 0) & (week >= 0) & (week < self.n_weeks)
        if keep is not None:
            ok &= keep
        flat = tbin[ok] * self.n_weeks + week[ok]
        self.risk[c] += np.bincount(flat, minlength=N_BINS * self.n_weeks).reshape(N_BINS, self.n_weeks)
        t = ok & trip
        flat = tbin[t] * self.n_weeks + week[t]
        self.trip[c] += np.bincount(flat, minlength=N_BINS * self.n_weeks).reshape(N_BINS, self.n_weeks)

    def pooled(self, classes):
        ix = [CLASSES.index(c) for c in classes]
        return self.risk[ix].sum(axis=0), self.trip[ix].sum(axis=0)


def ratio(risk, trip, num, den):
    """(hazard in bins num) / (hazard in bins den), with counts; risk and trip
    are (N_BINS, n_weeks) arrays."""
    rn, tn = int(risk[list(num)].sum()), int(trip[list(num)].sum())
    rd, td = int(risk[list(den)].sum()), int(trip[list(den)].sum())
    out = {"num_risk": rn, "num_trips": tn, "den_risk": rd, "den_trips": td, "ratio": None,
           "hazard_num": tn / rn if rn else None, "hazard_den": td / rd if rd else None}
    if rn and rd and td:
        out["ratio"] = (tn / rn) / (td / rd)
    out["ok"] = bool(tn >= 30 and rn >= 10000 and td >= 30 and out["ratio"] is not None)
    return out


def ratio_ci(risk, trip, num, den, reps=2000, seed=20261117):
    """95% interval of ratio() from a bootstrap that resamples whole weeks
    (all units together, so cold snaps stay intact)."""
    rng = np.random.default_rng(seed)
    nw = risk.shape[1]
    rn, tn = risk[list(num)].sum(axis=0), trip[list(num)].sum(axis=0)
    rd, td = risk[list(den)].sum(axis=0), trip[list(den)].sum(axis=0)
    vals = []
    for _ in range(reps):
        m = np.bincount(rng.integers(0, nw, nw), minlength=nw)
        a, b, c, e = rn @ m, tn @ m, rd @ m, td @ m
        if a > 0 and c > 0 and e > 0:
            vals.append((b / a) / (e / c))
    if len(vals) < reps * 0.9:
        return None, None
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def score(r):
    """r: name -> ratio() dict, names gas_cold, coal_cold, gas_cold_noevents,
    gas_cold_placebo, gas_hot, gas_near_freeze, gas_very_cold. Returns
    H1..H7 as True (held), False (failed) or None (not scorable)."""
    def v(k):
        x = r.get(k)
        return x["ratio"] if x and x.get("ok") else None

    g, co = v("gas_cold"), v("coal_cold")
    p = {"H1": None if g is None else g >= 3.0,
         "H2": None if co is None else co >= 1.5,
         "H3": None if g is None or co is None else g > co}
    ne = v("gas_cold_noevents")
    p["H4"] = None if ne is None else ne >= 2.0
    pl = v("gas_cold_placebo")
    p["H5"] = None if g is None or pl is None or pl <= 0 else g / pl >= 1.5
    h = v("gas_hot")
    p["H6"] = None if h is None else h > 1.0
    nf, vc = v("gas_near_freeze"), v("gas_very_cold")
    p["H7"] = None if nf is None or vc is None else (nf < 1.5 and vc >= 3.0)
    return p
