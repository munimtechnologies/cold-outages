# SPDX-License-Identifier: Apache-2.0
"""truth-1 core: check fossil-unit trips found in EPA's public hourly data
(the outage-1 rule, unchanged) against ERCOT's official unit-level list of
generator outages and derates during Winter Storm Uri (February 10-19, 2021,
file Unit_Outage_Data_20210312.xlsx, published under a PUC of Texas order).

Pure Python (standard library only). The plan, with every definition and
prediction, is docs/truth-plan.md (Pre-registration id: truth-1).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's
name. Apache-2.0.
"""
import datetime as dt
import io
import re
import zipfile
import xml.etree.ElementTree as ET

UTC = dt.timezone.utc
CST_OFFSET = dt.timedelta(hours=6)   # ERCOT times are Central; Feb 2021 = CST = UTC-6
TOL_H = 3.0                          # |ERCOT start - CEMS trip start| allowed, hours
CAP_LO, CAP_HI = 0.25, 4.0           # ERCOT unit size / CEMS capability allowed range
FULL_FRAC = 0.02                     # full outage: available <= 2% of seasonal max
MIN_MW = 25.0                        # ERCOT records below this size are not in recall
RUN_BEFORE_H = 6                     # recall eligibility: ran hard in the 6 h before
PLACEBO_SHIFTS_H = (-24.0, 24.0)
PRIMARY = (dt.datetime(2021, 2, 14, 6, tzinfo=UTC), dt.datetime(2021, 2, 20, 6, tzinfo=UTC))
COVER = (dt.datetime(2021, 2, 10, 6, tzinfo=UTC), dt.datetime(2021, 2, 20, 6, tzinfo=UTC))
MIN_TRIPS_V1 = 30
MIN_ELIG_V2 = 20
V1_BAR, V2_BAR, V3_FACTOR, V4_BAR = 0.70, 0.50, 2.0, 0.80

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

FIELDS = ("station_code", "station", "unit", "seasonal_mw", "available_mw", "reduction_mw",
          "fuel", "start", "end", "county", "entity")
# Column order reported for the file when no header row can be recognised.
FALLBACK_ORDER = {"station_code": 0, "station": 1, "unit": 2, "seasonal_mw": 3, "available_mw": 4,
                  "reduction_mw": 5, "fuel": 6, "start": 7, "end": 8}

COAL_TOKENS = frozenset({"COAL", "LIG", "LIGNITE", "SUB", "BIT", "CLLIG", "SUBBIT", "COALLIG"})
GAS_TOKENS = frozenset({"NG", "GAS", "NATURAL", "CC", "CCGT", "CCLE", "GT", "CT", "SCGT", "SCLE",
                        "GSREH", "GSNONR", "GSSUP", "STEAM"})
OIL_TOKENS = frozenset({"OIL", "DFO", "FO", "DIESEL", "RFO"})
NONFOSSIL_TOKENS = frozenset({"NUC", "NUCLEAR", "WIND", "WND", "SOLAR", "SUN", "PV", "PVGR", "HYDRO",
                              "WAT", "WATER", "PWRSTR", "STORAGE", "BATTERY", "ESR", "BIOMASS",
                              "LANDFILL", "LFG", "WOOD"})


# ---------------------------------------------------------------- xlsx reading
def col_index(ref):
    """'A1' -> 0, 'C7' -> 2, 'AA3' -> 26."""
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx(data):
    """xlsx bytes -> ([(sheet name, rows)], date1904). rows: lists of cell
    values (str, float or None), one list per <row> element."""
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    shared = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.iter(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    pr = wb.find(NS + "workbookPr")
    d1904 = pr is not None and str(pr.get("date1904", "")).lower() in ("1", "true")
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
            rels[r.get("Id")] = r.get("Target") or ""
    sheets = []
    sh_el = wb.find(NS + "sheets")
    for i, s in enumerate(list(sh_el) if sh_el is not None else []):
        tgt = (rels.get(s.get(RNS + "id")) or "worksheets/sheet%d.xml" % (i + 1)).lstrip("/")
        path = tgt if tgt.startswith("xl/") else "xl/" + tgt
        if path in names:
            sheets.append((s.get("name") or "sheet%d" % (i + 1), path))
    out = []
    for name, path in sheets:
        root = ET.fromstring(z.read(path))
        rows = []
        for row in root.iter(NS + "row"):
            vals = {}
            for c in row.findall(NS + "c"):
                t = c.get("t")
                v = c.find(NS + "v")
                if t == "s" and v is not None and v.text is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    isel = c.find(NS + "is")
                    val = "".join(x.text or "" for x in isel.iter(NS + "t")) if isel is not None else None
                elif v is None or v.text is None:
                    val = None
                elif t in ("str", "e", "b"):
                    val = v.text
                else:
                    try:
                        val = float(v.text)
                    except ValueError:
                        val = v.text
                ci = col_index(c.get("r"))
                vals[len(vals) if ci is None else ci] = val
            rows.append([vals.get(k) for k in range(max(vals) + 1)] if vals else [])
        out.append((name, rows))
    return out, d1904


# ---------------------------------------------------------------- cell parsing
def norm_text(x):
    return re.sub(r"\s+", " ", "" if x is None else str(x)).strip().upper()


def map_header(row):
    """Header row -> {field: column}. First matching column wins."""
    m = {}
    for i, cell in enumerate(row):
        h = norm_text(cell)
        if not h:
            continue
        f = None
        if "START" in h or "BEGIN" in h:
            f = "start"
        elif re.search(r"\bEND\b", h):
            f = "end"
        elif "SEASONAL" in h or re.search(r"\bMAX", h):
            f = "seasonal_mw"
        elif "AVAIL" in h or "REMAIN" in h:
            f = "available_mw"
        elif "REDUC" in h:
            f = "reduction_mw"
        elif "FUEL" in h:
            f = "fuel"
        elif "COUNTY" in h:
            f = "county"
        elif "ENTITY" in h or "OWNER" in h:
            f = "entity"
        elif "UNIT" in h and "CODE" not in h:
            f = "unit"
        elif "STATION" in h or "PLANT" in h or "SITE" in h:
            f = "station_code" if ("CODE" in h or h.endswith(" ID")) else "station"
        if f and f not in m:
            m[f] = i
    return m


def header_ok(m):
    return "start" in m and "county" in m and any(k in m for k in ("seasonal_mw", "reduction_mw", "available_mw"))


def to_num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def excel_serial(x, d1904=False):
    base = dt.datetime(1904, 1, 1) if d1904 else dt.datetime(1899, 12, 30)
    minutes = int(round(float(x) * 1440.0))
    return base + dt.timedelta(minutes=minutes)


TIME_FORMATS = ("%m/%d/%y %I:%M %p", "%m/%d/%Y %I:%M %p", "%m/%d/%y %I:%M:%S %p", "%m/%d/%Y %I:%M:%S %p",
                "%m/%d/%y %H:%M", "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M")


def parse_local(x, d1904=False):
    """Cell -> naive Central-time datetime, or None."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return excel_serial(x, d1904) if 30000 < x < 60000 else None
    s = re.sub(r"\s+", " ", str(x)).strip()
    if not s:
        return None
    try:
        f = float(s)
        return excel_serial(f, d1904) if 30000 < f < 60000 else None
    except ValueError:
        pass
    for fmt in TIME_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def central_to_utc(local):
    return None if local is None else (local + CST_OFFSET).replace(tzinfo=UTC)


def norm_county(x):
    u = re.sub(r"\bCOUNTY\b", "", norm_text(x))
    return re.sub(r"[^A-Z]", "", u)


def fuel_group(x):
    toks = set(re.findall(r"[A-Z]+", norm_text(x)))
    if not toks:
        return "UNKNOWN"
    if toks & NONFOSSIL_TOKENS:
        return "NONFOSSIL"
    if toks & COAL_TOKENS:
        return "COAL"
    if toks & GAS_TOKENS:
        return "GAS"
    if toks & OIL_TOKENS:
        return "OIL"
    return "OTHER"


def entity_like(x):
    return bool(re.search(r"\b(LLC|LP|L P|INC|CORP|COMPANY|CO-OP|COOP|AUTHORITY)\b|\(RE\)", norm_text(x)))


# ---------------------------------------------------------------- records
def find_layout(rows, d1904=False):
    """-> ("header", header row index, map) or ("fallback", None, map) or (None, None, {})."""
    for i, row in enumerate(rows[:40]):
        m = map_header(row)
        if header_ok(m):
            return "header", i, m
    good = tot = 0
    for row in rows:
        if len(row) < 10:
            continue
        tot += 1
        if to_num(row[3]) is not None and to_num(row[5]) is not None and parse_local(row[7], d1904):
            good += 1
    if tot and good * 2 >= tot:
        m = dict(FALLBACK_ORDER)
        # county and entity: whichever of columns 9 and 10 looks less like company names is county
        e9 = sum(1 for r in rows if len(r) > 9 and entity_like(r[9]))
        e10 = sum(1 for r in rows if len(r) > 10 and entity_like(r[10]))
        m["county"], m["entity"] = (10, 9) if e9 > e10 else (9, 10)
        return "fallback", None, m
    return None, None, {}


def make_record(row, m, d1904=False):
    def get(f):
        i = m.get(f)
        return row[i] if (i is not None and i < len(row)) else None
    start = parse_local(get("start"), d1904)
    if start is None:
        return None
    end = parse_local(get("end"), d1904)
    seas, avail, red = to_num(get("seasonal_mw")), to_num(get("available_mw")), to_num(get("reduction_mw"))
    if red is None and seas is not None and avail is not None:
        red = seas - avail
    if avail is None and seas is not None and red is not None:
        avail = seas - red
    fuel = norm_text(get("fuel"))
    county_n = norm_county(get("county"))
    full = None
    if seas is not None and seas > 0 and avail is not None:
        full = avail <= FULL_FRAC * seas
    size = seas if (seas is not None and seas > 0) else red
    fg = fuel_group(fuel)
    return {"station_code": norm_text(get("station_code")), "station": norm_text(get("station")),
            "unit": norm_text(get("unit")), "entity": norm_text(get("entity")), "county": norm_text(get("county")),
            "county_n": county_n, "fuel": fuel, "fuel_group": fg, "fossil": fg in ("COAL", "GAS", "OIL"),
            "seasonal_mw": seas, "available_mw": avail, "reduction_mw": red, "size_mw": size, "full": full,
            "start_utc": central_to_utc(start), "end_utc": central_to_utc(end), "redacted": not county_n}


def parse_records(sheets, d1904=False):
    """Sheets from read_xlsx -> (records, info). Uses every sheet whose layout
    is recognised by a header row; if none is, the fallback column order on
    the sheet with most rows."""
    recs, info = [], {"sheets": []}
    used = False
    for name, rows in sheets:
        mode, hi, m = find_layout(rows, d1904)
        entry = {"sheet": name, "rows": len(rows), "mode": mode, "header_row": hi, "map": m}
        info["sheets"].append(entry)
        if mode != "header":
            continue
        used = True
        n0 = len(recs)
        for k in range(hi + 1, len(rows)):
            r = make_record(rows[k], m, d1904)
            if r is not None:
                r["sheet"], r["row"] = name, k
                recs.append(r)
        entry["records"] = len(recs) - n0
    if not used and sheets:
        name, rows = max(sheets, key=lambda s: len(s[1]))
        mode, hi, m = find_layout(rows, d1904)
        if mode == "fallback":
            n0 = len(recs)
            for k, row in enumerate(rows):
                r = make_record(row, m, d1904)
                if r is not None:
                    r["sheet"], r["row"] = name, k
                    recs.append(r)
            info["fallback_sheet"] = name
            info["fallback_records"] = len(recs) - n0
    info["records"] = len(recs)
    return recs, info


# ---------------------------------------------------------------- matching
def cap_ok(size_mw, cap):
    if size_mw is None or size_mw <= 0 or cap is None or cap <= 0:
        return True
    return CAP_LO * cap <= size_mw <= CAP_HI * cap


def matches(t, recs, shift_h=0.0, tol_h=TOL_H, check_cap=True):
    """Indices of fossil, non-redacted records in the trip's county whose
    start is within tol_h hours of the trip start (+ shift) and whose size
    fits the unit. t: {"county_n", "cap", "start_utc"}."""
    tt = t["start_utc"] + dt.timedelta(hours=shift_h)
    out = []
    for i, r in enumerate(recs):
        if r["redacted"] or not r["fossil"] or r["county_n"] != t["county_n"]:
            continue
        if abs((r["start_utc"] - tt).total_seconds()) > tol_h * 3600.0:
            continue
        if check_cap and not cap_ok(r["size_mw"], t["cap"]):
            continue
        out.append(i)
    return out


def precision(trips, recs, shift_h=0.0, tol_h=TOL_H, check_cap=True, window=PRIMARY, cover=COVER):
    """(confirmed, total) over trips with a known county starting in window;
    with a shift, only trips whose shifted time lies inside cover."""
    k = n = 0
    for t in trips:
        if not t["county_n"] or not (window[0] <= t["start_utc"] < window[1]):
            continue
        if shift_h:
            ts = t["start_utc"] + dt.timedelta(hours=shift_h)
            if not (cover[0] <= ts < cover[1]):
                continue
        n += 1
        if matches(t, recs, shift_h, tol_h, check_cap):
            k += 1
    return k, n


def placebo_precision(trips, recs, shifts=PLACEBO_SHIFTS_H):
    k = n = 0
    for s in shifts:
        a, b = precision(trips, recs, shift_h=s)
        k += a
        n += b
    return k, n


def ehour(t):
    return int(t.timestamp()) // 3600


def recall(recs, units, trips, tol_h=TOL_H, check_cap=True, window=PRIMARY):
    """(found, eligible). Eligible: fossil, non-redacted, full-outage record
    of at least MIN_MW starting in window, with a CEMS unit in the same
    county, of fitting size, that ran hard in one of the RUN_BEFORE_H hours
    before the record's start hour. units: {"county_n", "cap", "hard": set of
    epoch hours}. Found: some trip in that county, of fitting size, starting
    within tol_h hours of the record."""
    by_county = {}
    for u in units:
        by_county.setdefault(u["county_n"], []).append(u)
    tby = {}
    for t in trips:
        tby.setdefault(t["county_n"], []).append(t)
    found = elig = 0
    for r in recs:
        if r["redacted"] or not r["fossil"] or r["full"] is not True:
            continue
        if r["size_mw"] is None or r["size_mw"] < MIN_MW:
            continue
        if not (window[0] <= r["start_utc"] < window[1]):
            continue
        sh = ehour(r["start_utc"])
        ok = False
        for u in by_county.get(r["county_n"], []):
            if check_cap and not cap_ok(r["size_mw"], u["cap"]):
                continue
            if any((h in u["hard"]) for h in range(sh - RUN_BEFORE_H, sh)):
                ok = True
                break
        if not ok:
            continue
        elig += 1
        for t in tby.get(r["county_n"], []):
            if check_cap and not cap_ok(r["size_mw"], t["cap"]):
                continue
            if abs((r["start_utc"] - t["start_utc"]).total_seconds()) <= tol_h * 3600.0:
                found += 1
                break
    return found, elig


def ercot_curve(recs, h0, n, fossil_only=True):
    """MW of records in effect at the middle of each hour h0..h0+n-1 (epoch hours)."""
    curve = [0.0] * n
    for r in recs:
        if (fossil_only and not r["fossil"]) or r["reduction_mw"] is None or r["reduction_mw"] <= 0:
            continue
        s = r["start_utc"].timestamp()
        e = r["end_utc"].timestamp() if r["end_utc"] is not None else float("inf")
        for k in range(n):
            mid = (h0 + k) * 3600 + 1800
            if s <= mid < e:
                curve[k] += r["reduction_mw"]
    return curve


def pearson(xs, ys):
    n = len(xs)
    if n != len(ys) or n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def score(prec, prec_placebo, rec, r):
    """V1..V4 as True (held), False (failed) or None (not scorable)."""
    v = {}
    k, n = prec
    v["V1"] = None if n < MIN_TRIPS_V1 else (k / n >= V1_BAR)
    fk, fn = rec
    v["V2"] = None if fn < MIN_ELIG_V2 else (fk / fn >= V2_BAR)
    pk, pn = prec_placebo
    if n < MIN_TRIPS_V1 or pn == 0:
        v["V3"] = None
    else:
        p, q = k / n, pk / pn
        v["V3"] = (p > 0) if q == 0 else (p >= V3_FACTOR * q)
    v["V4"] = None if r is None else (r >= V4_BAR)
    return v
