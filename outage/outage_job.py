# SPDX-License-Identifier: Apache-2.0
"""outage-1 job: rebuild fossil-unit trips during seven U.S. cold-weather
grid events (2011-2026) from EPA's public hourly emissions data, and compare
them with the official FERC/NERC outage totals. See docs/outage-plan.md
(pre-registered before any hourly data was read).

Data (all public, no key): Catalyst Cooperative's PUDL nightly build
(CC BY 4.0) of EPA CEMS hourly emissions, EIA-860 plants and generators, and
the EPA-EIA unit crosswalk.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's
name. Apache-2.0.
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import outage_core as core  # noqa: E402

import numpy as np  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.compute as pc  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

BASE = "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/"
UA = {"User-Agent": "mv2-outage-1/0.1 (MV2 of Munim, Inc.; mv2@munimtech.com)"}
PARAMS = {"main": {}, "off4": {"off_hours": 4}, "off12": {"off_hours": 12}}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def wait_for(url, token, minutes):
    """Do not read any hourly data until the plan is public."""
    deadline = time.time() + minutes * 60
    while True:
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                if token in r.read().decode("utf-8", "replace"):
                    log("plan live:", url)
                    return True
        except Exception as e:  # noqa: BLE001
            log("plan check failed:", e)
        if time.time() > deadline:
            log("plan not live after", minutes, "minutes; stopping")
            return False
        time.sleep(300)


def download(name, data_dir):
    path = os.path.join(data_dir, name)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        log("cached", name, os.path.getsize(path))
        return path
    tmp = path + ".part"
    req = urllib.request.Request(BASE + name, headers=UA)
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
        x = x.replace(tzinfo=core.UTC) if x.tzinfo is None else x.astimezone(core.UTC)
        return dt.datetime(x.year, x.month, x.day, x.hour, tzinfo=core.UTC)
    return None


def plain(col):
    if pa.types.is_dictionary(col.type):
        return col.cast(col.type.value_type)
    return col


def plain_table(t):
    for i, name in enumerate(t.column_names):
        if pa.types.is_dictionary(t.schema.field(i).type):
            t = t.set_column(i, name, plain(t.column(i)))
    return t


def ehour(x):
    return int(x.timestamp()) // 3600


def from_ehour(h):
    return dt.datetime.fromtimestamp(h * 3600, tz=core.UTC)


def epoch_hours(col):
    """UTC timestamps -> whole hours since 1970 (int64); nulls -> 0."""
    if isinstance(col, pa.ChunkedArray):
        col = col.combine_chunks()
    div = {"s": 3600, "ms": 3600 * 10 ** 3, "us": 3600 * 10 ** 6, "ns": 3600 * 10 ** 9}[col.type.unit]
    iv = pc.fill_null(pc.cast(col, pa.int64()), 0)
    return iv.to_numpy(zero_copy_only=False).astype(np.int64) // div


def read_ba_rows(path):
    t = plain_table(pq.read_table(path, columns=["plant_id_eia", "report_date", "balancing_authority_code_eia"]))
    rows = {}
    for r in t.to_pylist():
        rd = as_date(r["report_date"])
        if r["plant_id_eia"] is None or rd is None:
            continue
        rows.setdefault(r["plant_id_eia"], []).append((rd.year, r["balancing_authority_code_eia"] or ""))
    log("plants with BA rows:", len(rows))
    return rows


def read_fuel(gpath, spath):
    """(plant, EPA unit) -> fuel class, from the crosswalk generators' latest
    EIA-860 energy source and capacity."""
    g = plain_table(pq.read_table(gpath, columns=["plant_id_eia", "generator_id", "report_date",
                                                  "energy_source_code_1", "capacity_mw"]))
    latest = {}
    for r in g.to_pylist():
        rd = as_date(r["report_date"])
        if rd is None or r["plant_id_eia"] is None or r["generator_id"] is None:
            continue
        k = (r["plant_id_eia"], str(r["generator_id"]))
        if k not in latest or rd > latest[k][0]:
            latest[k] = (rd, r["energy_source_code_1"], r["capacity_mw"])
    s = plain_table(pq.read_table(spath, columns=["plant_id_eia", "emissions_unit_id_epa", "generator_id"]))
    gens = {}
    for r in s.to_pylist():
        if r["plant_id_eia"] is None or not r["emissions_unit_id_epa"] or not r["generator_id"]:
            continue
        gens.setdefault((r["plant_id_eia"], str(r["emissions_unit_id_epa"])), set()).add(str(r["generator_id"]))
    fuel = {}
    for (p, u), gs in gens.items():
        caps = {}
        for gid in gs:
            v = latest.get((p, gid))
            if v and v[1]:
                caps[v[1]] = caps.get(v[1], 0.0) + (v[2] or 0.0)
        fuel[(p, u)] = core.fuel_class(caps)
    log("units with fuel:", len(fuel))
    return fuel


def read_names(path):
    try:
        t = plain_table(pq.read_table(path, columns=["plant_id_eia", "plant_name_eia"]))
        return {r["plant_id_eia"]: r["plant_name_eia"] for r in t.to_pylist()}
    except Exception as e:  # noqa: BLE001
        log("plant names unavailable:", e)
        return {}


def cems_open(url):
    f = HttpRangeFile(url)
    pf = pq.ParquetFile(f)
    md = pf.metadata
    idx = {md.row_group(0).column(i).path_in_schema: i for i in range(md.num_columns)}
    log("cems columns:", pf.schema_arrow.names, "row groups:", md.num_row_groups, "size:", f.size)
    years, maxyear = {}, None
    for g in range(md.num_row_groups):
        st = md.row_group(g).column(idx["year"]).statistics
        if st is not None and st.has_min_max:
            years[g] = (int(st.min), int(st.max))
            maxyear = int(st.max) if maxyear is None else max(maxyear, int(st.max))
        else:
            years[g] = None
    cov = None
    for g in range(md.num_row_groups):
        if years[g] is not None and years[g][1] != maxyear:
            continue
        st = md.row_group(g).column(idx["operating_datetime_utc"]).statistics
        m = to_utc(st.max) if (st is not None and st.has_min_max) else None
        if m is None:
            tt = pf.read_row_group(g, columns=["operating_datetime_utc"])
            m = to_utc(pc.max(tt["operating_datetime_utc"]).as_py())
        if m is not None and (cov is None or m > cov):
            cov = m
    log("CEMS max year:", maxyear, "coverage max hour:", cov)
    return f, pf, years, cov


class Store:
    """Hourly gross load (MW, int16, absent rows = 0) per unit per window."""

    def __init__(self, windows):
        self.windows = windows
        self.units, self.key, self.state = [], {}, []
        self.cap = 8192
        self.arr = [np.zeros((self.cap, w["n"]), dtype=np.int16) for w in windows]

    def gid(self, plant, unit, state):
        k = (plant, unit)
        g = self.key.get(k)
        if g is None:
            g = len(self.units)
            self.key[k] = g
            self.units.append(k)
            self.state.append(state)
            if g >= self.cap:
                extra = self.cap
                self.arr = [np.vstack([a, np.zeros((extra, a.shape[1]), dtype=np.int16)]) for a in self.arr]
                self.cap += extra
        elif not self.state[g] and state:
            self.state[g] = state
        return g


def read_cems(pf, f, years_of_group, windows, store):
    need = set()
    for w in windows:
        for y in range(from_ehour(w["h0"]).year, from_ehour(w["h0"] + w["n"] - 1).year + 1):
            need.add(y)
    log("CEMS years needed:", sorted(need))
    cols = ["plant_id_eia", "emissions_unit_id_epa", "operating_datetime_utc", "gross_load_mw", "state"]
    groups = [g for g in sorted(years_of_group)
              if years_of_group[g] is None or any(years_of_group[g][0] <= y <= years_of_group[g][1] for y in need)]
    log("row groups to read:", len(groups), "of", len(years_of_group))
    rows_kept = 0
    for n, g in enumerate(groups):
        t = pf.read_row_group(g, columns=cols)
        hrs = epoch_hours(t["operating_datetime_utc"])
        anym = np.zeros(len(hrs), dtype=bool)
        for w in windows:
            anym |= (hrs >= w["h0"]) & (hrs < w["h0"] + w["n"])
        if not anym.any():
            continue
        sel = np.nonzero(anym)[0]
        t = plain_table(t.take(pa.array(sel)))
        hrs = hrs[sel]
        plant = pc.fill_null(t["plant_id_eia"], -1).to_numpy().astype(np.int64)
        ucol = pc.dictionary_encode(pc.fill_null(t["emissions_unit_id_epa"], "").combine_chunks())
        uidx = ucol.indices.to_numpy(zero_copy_only=False).astype(np.int64)
        udict = ucol.dictionary.to_pylist()
        scol = pc.dictionary_encode(pc.fill_null(t["state"], "").combine_chunks())
        sidx = scol.indices.to_numpy(zero_copy_only=False).astype(np.int64)
        sdict = scol.dictionary.to_pylist()
        load = np.nan_to_num(t["gross_load_mw"].to_numpy().astype(np.float64), nan=0.0)
        load = np.rint(np.clip(load, 0, 32000)).astype(np.int16)
        local = plant * (len(udict) + 1) + uidx
        uniq, first, inv = np.unique(local, return_index=True, return_inverse=True)
        gmap = np.array([store.gid(int(plant[i]), str(udict[uidx[i]]), sdict[sidx[i]]) for i in first],
                        dtype=np.int64)
        gidx = gmap[np.asarray(inv).reshape(-1)]
        for wi, w in enumerate(windows):
            m = (hrs >= w["h0"]) & (hrs < w["h0"] + w["n"])
            if m.any():
                store.arr[wi][gidx[m], hrs[m] - w["h0"]] = load[m]
        rows_kept += len(sel)
        if n % 10 == 0:
            log("row group", n, "of", len(groups), "rows kept", rows_kept, "units", len(store.units),
                "fetched MB", round(f.fetched / 1e6, 1))
    log("CEMS done; rows kept", rows_kept, "units", len(store.units), "fetched MB", round(f.fetched / 1e6, 1))


def analyse_window(w, store, wi, ba_rows, fuel, names, keep_trips):
    """Series per (param, area) and, for the main setting, trips and fuel rates."""
    ev = w["event"]
    areas = list(dict.fromkeys([ev["area"], "EAST_TX", "ERCOT"]))  # no duplicates
    ws, we = w["ws"], w["we"]
    series = {(p, a): [0.0] * (we - ws) for p in PARAMS for a in areas}
    trip_cap, elig_cap, trips_out, n_main = {}, {}, [], 0
    arr = store.arr[wi]
    year = ev["start"].year
    active = np.nonzero(arr[:, max(0, ws - 3):we].max(axis=1) > 0)[0]
    for g in active.tolist():
        plant, unit = store.units[g]
        state = store.state[g]
        ba = core.ba_for_year(ba_rows.get(plant, []), year)
        member = [a for a in areas if core.in_area(a, ba, state)]
        if not member:
            continue
        loads = arr[g].tolist()
        cap = core.unit_cap(loads, we)
        if cap < core.MIN_CAP_MW:
            continue
        fc = fuel.get((plant, unit), "UNKNOWN")
        for p, kw in PARAMS.items():
            trips, contrib = core.detect(loads, ws, we, cap, **kw)
            if not trips:
                continue
            for a in member:
                s = series[(p, a)]
                for k, v in enumerate(contrib):
                    if v:
                        s[k] += v
            if p == "main" and ev["area"] in member:
                n_main += len(trips)
            if p == "main" and ev["area"] in member and keep_trips:
                for (i, j) in trips:
                    trips_out.append({
                        "plant_id_eia": plant, "plant_name": names.get(plant, ""), "unit": unit,
                        "state": state, "ba": ba or "", "fuel": fc, "cap_mw": cap,
                        "trip_start_utc": from_ehour(w["h0"] + i).isoformat(),
                        "back_utc": "" if j is None else from_ehour(w["h0"] + j).isoformat(),
                        "hours_off": "" if j is None else j - i})
        if ev["area"] in member and core.ran_hard(loads, ws - 3, we, cap):
            elig_cap[fc] = elig_cap.get(fc, 0.0) + cap
            if core.detect(loads, ws, we, cap)[0]:
                trip_cap[fc] = trip_cap.get(fc, 0.0) + cap
    out = {}
    for (p, a), s in series.items():
        v, at = core.peak(s)
        out["%s|%s" % (p, a)] = {"peak_mw": round(v, 1),
                                 "peak_hour_utc": None if at is None else from_ehour(w["h0"] + ws + at).isoformat()}
    rate = {fc: (trip_cap.get(fc, 0.0) / elig_cap[fc]) for fc in elig_cap if elig_cap[fc] > 0}
    return out, rate, trip_cap, elig_cap, trips_out, len(active), n_main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--wait-for", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--minutes", type=int, default=240)
    a = ap.parse_args()
    os.makedirs(a.data_dir, exist_ok=True)
    os.makedirs(a.out_dir, exist_ok=True)
    if a.wait_for and not wait_for(a.wait_for, a.token, a.minutes):
        sys.exit(3)

    gpath = download("core_eia860__scd_generators.parquet", a.data_dir)
    ppath = download("core_eia860__scd_plants.parquet", a.data_dir)
    spath = download("core_epa__assn_eia_epacamd_subplant_ids.parquet", a.data_dir)
    try:
        names = read_names(download("core_eia__entity_plants.parquet", a.data_dir))
    except Exception as e:  # noqa: BLE001
        log("entity_plants download failed:", e)
        names = {}
    ba_rows = read_ba_rows(ppath)
    fuel = read_fuel(gpath, spath)

    f, pf, years_of_group, cov = cems_open(BASE + "core_epacems__hourly_emissions.parquet")
    if cov is None:
        sys.exit("no CEMS coverage")
    coverage_end = cov + core.HOUR

    windows = []
    lb = core.LOOKBACK_DAYS * 24
    for ev in core.EVENTS:
        spans = []
        if ev["end"] + core.TAIL_HOURS * core.HOUR <= coverage_end:
            spans.append(("event", ev["start"], ev["end"]))
        for (s0, s1) in core.control_windows(ev, core.EVENTS, coverage_end):
            spans.append(("control", s0, s1))
        for kind, s0, s1 in spans:
            h0 = ehour(s0) - lb
            ws = lb
            we = ws + (ehour(s1) - ehour(s0))
            windows.append({"event": ev, "kind": kind, "start": s0, "end": s1, "h0": h0,
                            "ws": ws, "we": we, "n": we + core.TAIL_HOURS})
    log("windows:", [(w["event"]["id"], w["kind"], w["start"].date().isoformat(), w["end"].date().isoformat())
                     for w in windows])

    store = Store(windows)
    read_cems(pf, f, years_of_group, windows, store)

    results, ev_score, all_trips = {}, {}, []
    for wi, w in enumerate(windows):
        ev = w["event"]
        out, rate, tcap, ecap, trips, nactive, n_main = analyse_window(
            w, store, wi, ba_rows, fuel, names, keep_trips=(w["kind"] == "event"))
        r = results.setdefault(ev["id"], {"name": ev["name"], "area": ev["area"], "official_mw": ev["official_mw"],
                                          "event": None, "controls": []})
        entry = {"start": w["start"].isoformat(), "end": w["end"].isoformat(), "units_with_load": nactive,
                 "series": out, "fuel_rate": rate, "tripped_cap_by_fuel": tcap, "eligible_cap_by_fuel": ecap,
                 "n_trips": n_main}
        if w["kind"] == "event":
            r["event"] = entry
            for t in trips:
                t["event"] = ev["id"]
            all_trips.extend(trips)
        else:
            r["controls"].append(entry)
        log(ev["id"], w["kind"], w["start"].date(), "main peak MW",
            out["main|%s" % ev["area"]]["peak_mw"], "at", out["main|%s" % ev["area"]]["peak_hour_utc"])

    for k, r in results.items():
        main_key = "main|%s" % r["area"]
        if r["event"] is None:
            ev_score[k] = {"T": None, "official": r["official_mw"]}
            continue
        ev_score[k] = {"T": r["event"]["series"][main_key]["peak_mw"],
                       "controls": [cw["series"][main_key]["peak_mw"] for cw in r["controls"]],
                       "official": r["official_mw"],
                       "ercot_T": r["event"]["series"]["main|ERCOT"]["peak_mw"],
                       "rate": r["event"]["fuel_rate"]}
    preds = core.score(ev_score)
    ok = [k for k in sorted(ev_score) if ev_score[k].get("T") is not None]
    rho = core.spearman([ev_score[k]["T"] for k in ok], [ev_score[k]["official"] for k in ok])
    robust = {}
    for p in PARAMS:
        xs = [results[k]["event"]["series"]["%s|EAST_TX" % p]["peak_mw"] for k in ok]
        robust["%s|EAST_TX" % p] = core.spearman(xs, [ev_score[k]["official"] for k in ok])
        xs = [results[k]["event"]["series"]["%s|%s" % (p, results[k]["area"])]["peak_mw"] for k in ok]
        robust["%s|main_area" % p] = core.spearman(xs, [ev_score[k]["official"] for k in ok])

    out = {"preregistration": "outage-1", "generated_utc": dt.datetime.now(core.UTC).isoformat(),
           "cems_coverage_end_exclusive": coverage_end.isoformat(), "units_seen": len(store.units),
           "spearman_main": rho, "spearman_variants": robust, "predictions": preds,
           "events": results, "score_inputs": ev_score}
    with open(os.path.join(a.out_dir, "outage1.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    fields = ["event", "plant_id_eia", "plant_name", "unit", "state", "ba", "fuel", "cap_mw",
              "trip_start_utc", "back_utc", "hours_off"]
    with open(os.path.join(a.out_dir, "outage1_trips.csv"), "w", encoding="utf-8", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=fields)
        wtr.writeheader()
        for t in all_trips:
            wtr.writerow({k: t.get(k, "") for k in fields})

    lines = ["# outage-1 results (machine-written)", "",
             "CEMS through %s (exclusive). Units seen: %d." % (coverage_end.isoformat(), len(store.units)), "",
             "| event | area | official MW | CEMS trip peak MW | peak hour UTC | controls peak MW | ratio | trips |",
             "|---|---|---|---|---|---|---|---|"]
    for k in sorted(results):
        r = results[k]
        if r["event"] is None:
            lines.append("| %s | %s | %.0f | not in coverage | | | | |" % (k, r["area"], r["official_mw"]))
            continue
        s = r["event"]["series"]["main|%s" % r["area"]]
        cs = ", ".join("%.0f" % cw["series"]["main|%s" % r["area"]]["peak_mw"] for cw in r["controls"])
        lines.append("| %s | %s | %.0f | %.0f | %s | %s | %.2f | %d |" % (
            k, r["area"], r["official_mw"], s["peak_mw"], s["peak_hour_utc"], cs,
            s["peak_mw"] / r["official_mw"], r["event"]["n_trips"]))
    lines += ["", "Spearman (main): %s. Variants: %s" % (rho, robust), "",
              "Fuel trip rates (tripped cap / cap that ran hard), Elliott: %s; Winter 2026: %s" % (
                  results.get("E2022", {}).get("event", {}) and results["E2022"]["event"]["fuel_rate"],
                  results.get("E2026", {}).get("event", {}) and results["E2026"]["event"]["fuel_rate"]), "",
              "Predictions: " + ", ".join("%s=%s" % (k, {True: "held", False: "failed", None: "not scorable"}[v])
                                         for k, v in preds.items())]
    with open(os.path.join(a.out_dir, "outage1.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
