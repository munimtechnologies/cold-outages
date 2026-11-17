# SPDX-License-Identifier: Apache-2.0
"""temp-1 job: hourly trip hazard of U.S. coal and gas units by local air
temperature, 2016-2025, from EPA's public hourly emissions data (CEMS, via
Catalyst Cooperative's PUDL nightly build, CC BY 4.0) and NOAA ISD-Lite hourly
temperatures (AWS Open Data mirror). Plan: docs/temp-plan.md (Pre-registration
id: temp-1), written before any hourly data was read. Every definition comes
from outage/temp_core.py, which this job downloads from the public repository
unchanged and tests before use. Choices the plan left open are listed in
docs/temp-job.md (written before the job ran).

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's
name. Apache-2.0.
"""
import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import hashlib
import importlib
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_RAW = "https://raw.githubusercontent.com/munimtechnologies/cold-outages/main/"
CORE_FILES = {  # git blob sha1 of the pre-registered files (logged and checked)
    "outage/temp_core.py": "703e1b5249ebaac8dfe4355bd5b70751a8884ff3",
    "outage/test_temp_core.py": "2dd23bcdd158fd040357e29ac20edefb2191af70",
}
PUDL = "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/"
ISD = "https://noaa-isd-pds.s3.amazonaws.com/"
UA = {"User-Agent": "mv2-temp-1/0.1 (MV2 of Munim, Inc.; mv2@munimtech.com)"}
STATION_BEGIN_MAX = "20160101"   # station active from 2016 ...
STATION_END_MIN = "20240101"     # ... to at least 2024
SCORED_RULE = "abrupt"
core = None                      # temp_core, loaded in main()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def http_get(url, missing_ok=False, timeout=120):
    last = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if missing_ok and e.code in (403, 404):
                return None
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(2 ** attempt)
    if missing_ok:
        log("giving up on", url, last)
        return None
    raise last


def blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def load_core(work):
    """Fetch the pre-registered core and its tests, check them, run the tests."""
    d = os.path.join(work, "core")
    os.makedirs(d, exist_ok=True)
    shas = {}
    for path, want in CORE_FILES.items():
        data = http_get(REPO_RAW + path)
        got = blob_sha(data)
        shas[path] = {"expected": want, "got": got, "match": got == want}
        log("core file", path, "sha", got, "MATCH" if got == want else "DIFFERS FROM EXPECTED")
        with open(os.path.join(d, os.path.basename(path)), "wb") as fh:
            fh.write(data)
    r = subprocess.run([sys.executable, os.path.join(d, "test_temp_core.py")], capture_output=True, text=True)
    sys.stdout.write(r.stdout[-3000:])
    sys.stdout.write(r.stderr[-3000:])
    if r.returncode != 0:
        sys.exit("temp_core tests failed")
    sys.path.insert(0, d)
    return importlib.import_module("temp_core"), shas


def wait_for(url, token, minutes):
    deadline = time.time() + minutes * 60
    while True:
        try:
            if token in http_get(url).decode("utf-8", "replace"):
                log("plan live:", url)
                return True
        except Exception as e:  # noqa: BLE001
            log("plan check failed:", e)
        if time.time() > deadline:
            return False
        time.sleep(300)


def download(name, data_dir):
    path = os.path.join(data_dir, name)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        log("cached", name, os.path.getsize(path))
        return path
    tmp = path + ".part"
    req = urllib.request.Request(PUDL + name, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    os.replace(tmp, path)
    log("downloaded", name, os.path.getsize(path))
    return path


class HttpRangeFile(io.RawIOBase):
    """Read-only, seekable view of a remote file through HTTP Range requests."""

    def __init__(self, url, block=4 << 20):
        super().__init__()
        req = urllib.request.Request(url, method="HEAD", headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            self.size = int(r.headers["Content-Length"])
        self.url, self.pos, self.block = url, 0, block
        self._cs, self._cb = None, b""
        self.fetched = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        if whence == 0:
            self.pos = off
        elif whence == 1:
            self.pos += off
        else:
            self.pos = self.size + off
        return self.pos

    def _get(self, start, end):
        last = None
        for attempt in range(6):
            try:
                hdr = dict(UA)
                hdr["Range"] = "bytes=%d-%d" % (start, end - 1)
                req = urllib.request.Request(self.url, headers=hdr)
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = r.read()
                if len(data) != end - start:
                    raise IOError("short read %d of %d" % (len(data), end - start))
                self.fetched += len(data)
                return data
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 ** attempt)
        raise last

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        if n == 0:
            return b""
        if n >= self.block:
            data = self._get(self.pos, self.pos + n)
        else:
            if not (self._cs is not None and self._cs <= self.pos
                    and self.pos + n <= self._cs + len(self._cb)):
                end = min(self.size, self.pos + self.block)
                self._cb = self._get(self.pos, end)
                self._cs = self.pos
            off = self.pos - self._cs
            data = self._cb[off:off + n]
        self.pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def plain_table(t):
    for i, name in enumerate(t.column_names):
        if pa.types.is_dictionary(t.schema.field(i).type):
            t = t.set_column(i, name, t.column(i).cast(t.schema.field(i).type.value_type))
    return t


def as_date(x):
    if x is None:
        return None
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def to_utc(x):
    if isinstance(x, dt.datetime):
        return x.replace(tzinfo=dt.timezone.utc) if x.tzinfo is None else x.astimezone(dt.timezone.utc)
    return None


def epoch_hours(col):
    if isinstance(col, pa.ChunkedArray):
        col = col.combine_chunks()
    div = {"s": 3600, "ms": 3600 * 10 ** 3, "us": 3600 * 10 ** 6, "ns": 3600 * 10 ** 9}[col.type.unit]
    iv = pc.fill_null(pc.cast(col, pa.int64()), 0)
    return iv.to_numpy(zero_copy_only=False).astype(np.int64) // div


def iso(h):
    return dt.datetime.fromtimestamp(int(h) * 3600, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:00Z")


# ---------------------------------------------------------------- reference data

def read_classes(gpath, spath):
    g = plain_table(pq.read_table(gpath, columns=["plant_id_eia", "generator_id", "report_date",
                                                  "energy_source_code_1", "prime_mover_code", "capacity_mw"]))
    latest = {}
    for r in g.to_pylist():
        rd = as_date(r["report_date"])
        if rd is None or r["plant_id_eia"] is None or r["generator_id"] is None:
            continue
        k = (r["plant_id_eia"], str(r["generator_id"]))
        if k not in latest or rd > latest[k][0]:
            latest[k] = (rd, r["energy_source_code_1"], r["prime_mover_code"], r["capacity_mw"])
    s = plain_table(pq.read_table(spath, columns=["plant_id_eia", "emissions_unit_id_epa", "generator_id"]))
    gens = {}
    for r in s.to_pylist():
        if r["plant_id_eia"] is None or not r["emissions_unit_id_epa"] or not r["generator_id"]:
            continue
        gens.setdefault((r["plant_id_eia"], str(r["emissions_unit_id_epa"])), set()).add(str(r["generator_id"]))
    out = {}
    for (p, u), gs in gens.items():
        lst = []
        for gid in sorted(gs):
            v = latest.get((p, gid))
            if v:
                lst.append((v[1], v[2], v[3]))
        out[(p, u)] = core.unit_class(lst)
    log("units with a class:", len(out))
    return out


def read_plants(path):
    t = plain_table(pq.read_table(path, columns=["plant_id_eia", "plant_name_eia", "state", "latitude", "longitude"]))
    out = {}
    for r in t.to_pylist():
        if r["plant_id_eia"] is not None:
            out[r["plant_id_eia"]] = r
    log("plants:", len(out))
    return out


def read_stations():
    data = http_get(ISD + "isd-history.csv").decode("utf-8", "replace")
    out = []
    for r in csv.DictReader(io.StringIO(data)):
        if (r.get("CTRY") or "").strip() != "US":
            continue
        try:
            lat, lon = float(r["LAT"]), float(r["LON"])
        except (TypeError, ValueError):
            continue
        if lat == 0.0 and lon == 0.0:
            continue
        b, e = (r.get("BEGIN") or "").strip(), (r.get("END") or "").strip()
        if not (len(b) == 8 and len(e) == 8 and b <= STATION_BEGIN_MAX and e >= STATION_END_MIN):
            continue
        out.append(("%s-%s" % (r["USAF"].strip(), r["WBAN"].strip()), lat, lon))
    log("US stations active 2016-2024:", len(out))
    return out


class Isd:
    """Station-year temperature series: (filled float32 array or None, raw hour count)."""

    def __init__(self):
        self.cache = {}
        self.files = 0

    def _fetch(self, key):
        sid, year = key
        data = http_get(ISD + "isd-lite/data/%d/%s-%d.gz" % (year, sid, year), missing_ok=True, timeout=60)
        if data is None:
            return key, (None, 0)
        t = core.parse_isd_lite(data, year)
        n = int(np.count_nonzero(~np.isnan(t)))
        return key, (core.fill_gaps(t), n)

    def prefetch(self, keys):
        todo = [k for k in dict.fromkeys(keys) if k not in self.cache]
        with cf.ThreadPoolExecutor(12) as ex:
            for key, val in ex.map(self._fetch, todo):
                self.cache[key] = val
                self.files += 1

    def get(self, sid, year):
        if (sid, year) not in self.cache:
            self.prefetch([(sid, year)])
        return self.cache[(sid, year)]

    def drop_before(self, year):
        for k in [k for k in self.cache if k[1] < year]:
            del self.cache[k]


# ---------------------------------------------------------------- CEMS

def cems_open(url):
    f = HttpRangeFile(url)
    pf = pq.ParquetFile(f)
    md = pf.metadata
    idx = {md.row_group(0).column(i).path_in_schema: i for i in range(md.num_columns)}
    log("cems columns:", pf.schema_arrow.names, "row groups:", md.num_row_groups, "size:", f.size)
    span, cov = {}, None
    for g in range(md.num_row_groups):
        st = md.row_group(g).column(idx["operating_datetime_utc"]).statistics
        lo = hi = None
        if st is not None and st.has_min_max:
            lo, hi = to_utc(st.min), to_utc(st.max)
        if lo is None and "year" in idx:
            sy = md.row_group(g).column(idx["year"]).statistics
            if sy is not None and sy.has_min_max:
                lo = dt.datetime(int(sy.min), 1, 1, tzinfo=dt.timezone.utc)
                hi = dt.datetime(int(sy.max), 12, 31, 23, tzinfo=dt.timezone.utc)
        span[g] = None if lo is None else (lo.year, hi.year)
        if hi is not None and (cov is None or hi > cov):
            cov = hi
    nostat = sum(1 for v in span.values() if v is None)
    log("CEMS coverage max hour:", cov, "groups without stats:", nostat)
    return f, pf, span, cov


def read_year(pf, f, span, year, h0, n):
    """Hourly gross load (int16, absent rows 0) and row-present flags per unit."""
    cols = ["plant_id_eia", "emissions_unit_id_epa", "operating_datetime_utc", "gross_load_mw"]
    groups = [g for g in sorted(span) if span[g] is None or span[g][0] <= year <= span[g][1]]
    key, units = {}, []
    cap = 4096
    load = np.zeros((cap, n), dtype=np.int16)
    pres = np.zeros((cap, n), dtype=bool)
    rows = 0
    for gi, g in enumerate(groups):
        t = pf.read_row_group(g, columns=cols)
        hrs = epoch_hours(t["operating_datetime_utc"])
        m = (hrs >= h0) & (hrs < h0 + n)
        if not m.any():
            continue
        sel = np.nonzero(m)[0]
        t = plain_table(t.take(pa.array(sel)))
        hrs = hrs[sel] - h0
        plant = pc.fill_null(t["plant_id_eia"], -1).to_numpy().astype(np.int64)
        ucol = pc.dictionary_encode(pc.fill_null(t["emissions_unit_id_epa"], "").combine_chunks())
        uidx = ucol.indices.to_numpy(zero_copy_only=False).astype(np.int64)
        udict = ucol.dictionary.to_pylist()
        gl = t["gross_load_mw"].to_numpy().astype(np.float64)
        gl = np.rint(np.clip(np.nan_to_num(gl, nan=0.0), 0, 32000)).astype(np.int16)
        local = plant * (len(udict) + 1) + uidx
        _, first, inv = np.unique(local, return_index=True, return_inverse=True)
        gm = []
        for i in first:
            k = (int(plant[i]), str(udict[uidx[i]]))
            j = key.get(k)
            if j is None:
                j = len(units)
                key[k] = j
                units.append(k)
                if j >= cap:
                    load = np.vstack([load, np.zeros((cap, n), dtype=np.int16)])
                    pres = np.vstack([pres, np.zeros((cap, n), dtype=bool)])
                    cap *= 2
            gm.append(j)
        gidx = np.asarray(gm, dtype=np.int64)[np.asarray(inv).reshape(-1)]
        load[gidx, hrs] = gl
        pres[gidx, hrs] = True
        rows += len(sel)
        if gi % 20 == 0:
            log(year, "row group", gi, "of", len(groups), "rows", rows, "units", len(units),
                "fetched MB", round(f.fetched / 1e6, 1))
    log(year, "CEMS rows", rows, "units", len(units), "groups read", len(groups))
    return units, load[:len(units)], pres[:len(units)]


# ---------------------------------------------------------------- main

def lag1(t):
    out = np.full(t.size, np.nan, dtype=np.float32)
    out[1:] = t[:-1]
    return out


def main():
    global core
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--wait-for", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--years", default="")
    a = ap.parse_args()
    os.makedirs(a.data_dir, exist_ok=True)
    os.makedirs(a.out_dir, exist_ok=True)
    core, shas = load_core("/tmp/temp1")
    if a.wait_for and not wait_for(a.wait_for, a.token, a.minutes):
        sys.exit("plan not live")
    years = [int(y) for y in a.years.split(",")] if a.years else list(core.YEARS)

    classes = read_classes(download("core_eia860__scd_generators.parquet", a.data_dir),
                           download("core_epa__assn_eia_epacamd_subplant_ids.parquet", a.data_dir))
    plants = read_plants(download("core_eia__entity_plants.parquet", a.data_dir))
    stations = read_stations()
    st_lat = np.array([s[1] for s in stations])
    st_lon = np.array([s[2] for s in stations])
    cand_cache = {}

    def cands(p):
        if p not in cand_cache:
            r = plants.get(p) or {}
            lat, lon = r.get("latitude"), r.get("longitude")
            cand_cache[p] = [stations[j][0] for j in core.station_candidates(lat, lon, st_lat, st_lon)] \
                if lat is not None and lon is not None else []
        return cand_cache[p]

    f, pf, span, cov = cems_open(PUDL + "core_epacems__hourly_emissions.parquet")
    cov_end = core.ehour(cov) + 1 if cov is not None else None
    n_weeks = int(core.week_index([core.ehour(core.d(2026, 1, 1)) - 1])[0]) + 1
    rules = list(core.RULES) + ["reported"]
    C = {r: core.Counts(n_weeks) for r in rules}
    C["noevents"] = core.Counts(n_weeks)
    C["placebo"] = core.Counts(n_weeks)
    isd = Isd()
    unit_rows, cold_trips, diag = {}, [], {"years": {}}
    ref_and_cold = set(core.COLD) | set(core.REF)

    for year in years:
        h0 = core.ehour(core.d(year, 1, 1))
        n = core.year_hours(year)
        if cov_end is not None:
            n = min(n, cov_end - h0)
        if n <= 24:
            log(year, "outside CEMS coverage; skipped")
            continue
        units, load, pres = read_year(pf, f, span, year, h0, n)
        isd.drop_before(year - 1)
        pl_set = sorted({p for p, _ in units})
        isd.prefetch([(cands(p)[0], year) for p in pl_set if cands(p)])
        station = {}
        for p in pl_set:
            for sid in cands(p):
                arr, nobs = isd.get(sid, year)
                if arr is not None and nobs >= core.MIN_STATION_HOURS:
                    station[p] = sid
                    break
        isd.prefetch([(sid, year - 1) for sid in set(station.values())])
        hours = h0 + np.arange(n)
        wk = core.week_index(hours)
        keep_ne = ~core.event_mask(hours)
        tb_cache = {}
        dy = {"units": len(units), "units_scored": 0, "plants": len(pl_set), "plants_with_station": len(station),
              "class_units": {}, "risk_hours_with_temp": 0, "risk_hours": 0, "abrupt_trips_absent_rows": 0,
              "hours": int(n)}
        for g, (p, u) in enumerate(units):
            x = load[g].astype(np.float64)
            capmw = core.cap_np(x)
            if capmw < core.MIN_CAP_MW:
                continue
            cls = classes.get((p, u), "OTHER")
            dy["units_scored"] += 1
            dy["class_units"][cls] = dy["class_units"].get(cls, 0) + 1
            sid = station.get(p)
            if sid is None:
                tb = tbp = np.full(n, -1, dtype=np.int64)
                tlag = np.full(n, np.nan, dtype=np.float32)
            else:
                if sid not in tb_cache:
                    cur = isd.get(sid, year)[0][:n]
                    prev = isd.get(sid, year - 1)[0]
                    full = isd.get(sid, year)[0]
                    plc = core.shifted_temp(prev, full, core.PLACEBO_SHIFT_H)[:n]
                    tl = lag1(cur)
                    tb_cache[sid] = (core.temp_bin(tl), core.temp_bin(lag1(plc)), tl)
                tb, tbp, tlag = tb_cache[sid]
            for rule, kw in core.RULES.items():
                risk, trip = core.risk_trip(x, capmw, kw["prev_frac"], kw["off_hours"])
                C[rule].add(cls, risk, trip, tb, wk)
                if rule == SCORED_RULE:
                    C["noevents"].add(cls, risk, trip, tb, wk, keep=keep_ne)
                    C["placebo"].add(cls, risk, trip, tbp, wk)
                    dy["risk_hours"] += int(risk.sum())
                    dy["risk_hours_with_temp"] += int((risk & (tb >= 0)).sum())
                    off = kw["off_hours"]
                    ti = np.nonzero(trip)[0]
                    for i in ti:
                        if not pres[g, i:i + off].any():
                            dy["abrupt_trips_absent_rows"] += 1
                    k = (p, u)
                    row = unit_rows.setdefault(k, {"plant_id_eia": p, "unit": u, "class": cls, "cap_mw_max": 0.0,
                                                   "years": 0, "risk_all": 0, "trips_all": 0, "risk_cold": 0,
                                                   "trips_cold": 0, "risk_ref": 0, "trips_ref": 0})
                    row["class"] = cls
                    row["years"] += 1
                    row["cap_mw_max"] = max(row["cap_mw_max"], capmw)
                    cold = np.isin(tb, core.COLD)
                    ref = np.isin(tb, core.REF)
                    row["risk_all"] += int((risk & (tb >= 0)).sum())
                    row["trips_all"] += int((trip & (tb >= 0)).sum())
                    row["risk_cold"] += int((risk & cold).sum())
                    row["trips_cold"] += int((trip & cold).sum())
                    row["risk_ref"] += int((risk & ref).sum())
                    row["trips_ref"] += int((trip & ref).sum())
                    for i in np.nonzero(trip & cold)[0]:
                        cold_trips.append({"plant_id_eia": p, "unit": u, "class": cls, "cap_mw": round(capmw, 1),
                                           "hour_utc": iso(h0 + i), "temp_c_prev_hour": round(float(tlag[i]), 1),
                                           "station": sid, "rows_reported_in_off_hours": bool(pres[g, i:i + off].any())})
            xr = np.where(pres[g], x, np.nan)
            kw = core.RULES[SCORED_RULE]
            risk, trip = core.risk_trip(xr, capmw, kw["prev_frac"], kw["off_hours"])
            C["reported"].add(cls, risk, trip, tb, wk)
        diag["years"][year] = dy
        log(year, json.dumps(dy), "isd files", isd.files)
        del load, pres

    # ------------------------------------------------------------ results
    G, K = list(core.GAS_CLASSES), ["COAL"]

    def rat(cn, classes_, num, den, ci=True):
        risk, trip = C[cn].pooled(classes_)
        r = core.ratio(risk, trip, num, den)
        if ci and r["ratio"] is not None:
            r["ci95"] = core.ratio_ci(risk, trip, num, den)
        return r

    R = {"gas_cold": rat("abrupt", G, core.COLD, core.REF),
         "coal_cold": rat("abrupt", K, core.COLD, core.REF),
         "gas_cold_noevents": rat("noevents", G, core.COLD, core.REF),
         "gas_cold_placebo": rat("placebo", G, core.COLD, core.REF),
         "gas_hot": rat("abrupt", G, core.HOT, core.REF),
         "gas_near_freeze": rat("abrupt", G, core.NEAR_FREEZE, core.REF),
         "gas_very_cold": rat("abrupt", G, core.VERY_COLD, core.REF)}
    preds = core.score(R)
    desc = {}
    for rule in rules + ["placebo", "noevents"]:
        for cls in core.CLASSES:
            desc["%s|%s|cold" % (rule, cls)] = rat(rule, [cls], core.COLD, core.REF, ci=False)
        desc["%s|GAS|cold" % rule] = rat(rule, G, core.COLD, core.REF, ci=(rule != "abrupt"))
        desc["%s|COAL|very_cold" % rule] = rat(rule, K, core.VERY_COLD, core.REF, ci=False)
    curves = {}
    for rule in rules + ["placebo"]:
        for name, cl in [("GAS", G), ("COAL", K)] + [(c, [c]) for c in core.CLASSES]:
            risk, trip = C[rule].pooled(cl)
            rs, ts = risk.sum(axis=1), trip.sum(axis=1)
            curves["%s|%s" % (rule, name)] = [{"bin": b, "risk_hours": int(rs[b]), "trips": int(ts[b]),
                                               "hazard_per_1000h": (1000.0 * ts[b] / rs[b]) if rs[b] else None}
                                              for b in range(core.N_BINS)]
    out = {"preregistration": "temp-1", "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
           "core_files": shas, "cems_coverage_max_hour": None if cov is None else cov.isoformat(),
           "bins_edges_c": list(core.EDGES), "scored": R, "predictions": preds, "describe": desc,
           "curves": curves, "diagnostics": diag, "isd_files_read": isd.files,
           "stations_considered": len(stations)}
    with open(os.path.join(a.out_dir, "temp1.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    names = {p: (r.get("plant_name_eia") or "", r.get("state") or "") for p, r in plants.items()}
    fields = ["plant_id_eia", "plant_name", "state", "unit", "class", "cap_mw_max", "years", "risk_all",
              "trips_all", "risk_cold", "trips_cold", "risk_ref", "trips_ref"]
    with open(os.path.join(a.out_dir, "temp1_units.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for k in sorted(unit_rows):
            r = dict(unit_rows[k])
            r["plant_name"], r["state"] = names.get(k[0], ("", ""))
            r["cap_mw_max"] = round(r["cap_mw_max"], 1)
            w.writerow({f2: r.get(f2, "") for f2 in fields})
    cf_fields = ["plant_id_eia", "plant_name", "state", "unit", "class", "cap_mw", "hour_utc", "temp_c_prev_hour",
                 "station", "rows_reported_in_off_hours"]
    with open(os.path.join(a.out_dir, "temp1_cold_trips.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cf_fields)
        w.writeheader()
        for r in cold_trips:
            r = dict(r)
            r["plant_name"], r["state"] = names.get(r["plant_id_eia"], ("", ""))
            w.writerow({f2: r.get(f2, "") for f2 in cf_fields})

    def fmt(r):
        if r is None or r.get("ratio") is None:
            return "n/a"
        ci = r.get("ci95") or (None, None)
        s = "%.2f" % r["ratio"]
        if ci[0] is not None:
            s += " (95%% CI %.2f-%.2f)" % ci
        return s + " [%d/%d trips, %d/%d at-risk h]%s" % (r["num_trips"], r["den_trips"], r["num_risk"],
                                                          r["den_risk"], "" if r["ok"] else " NOT SCORABLE")
    word = {True: "held", False: "failed", None: "not scorable"}
    lines = ["# temp-1 results (machine-written)", "",
             "CEMS coverage to %s. ISD files read: %d." % (out["cems_coverage_max_hour"], isd.files), "",
             "| ratio | value |", "|---|---|"]
    lines += ["| %s | %s |" % (k, fmt(v)) for k, v in R.items()]
    lines += ["", "Predictions: " + ", ".join("%s=%s" % (k, word[v]) for k, v in preds.items()), "",
              "Gas cold ratio by rule: " + "; ".join("%s %s" % (rule, fmt(desc.get("%s|GAS|cold" % rule)))
                                                     for rule in rules)]
    with open(os.path.join(a.out_dir, "temp1.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
