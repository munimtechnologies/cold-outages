# SPDX-License-Identifier: Apache-2.0
"""truth-1 job: are the fossil-unit trips that the outage-1 rule finds in EPA's
public hourly data real? Checks them, during Winter Storm Uri, against ERCOT's
official unit-level list of generator outages and derates (Unit_Outage_Data_
20210312.xlsx, February 10-19, 2021). Plan: docs/truth-plan.md
(Pre-registration id: truth-1), written before any CEMS data was read and
before the ERCOT file was parsed.

The trip rule, capability and "ran hard" are the outage-1 definitions. This job
downloads outage/outage_core.py, outage/outage_job.py and
outage/test_outage_core.py from the public repository, logs their git blob
shas, runs the outage-1 tests, and only then reads data.

Data (all public, no key): ERCOT's file above; Catalyst Cooperative's PUDL
nightly build (CC BY 4.0) of EPA CEMS hourly emissions, EIA-860 plants and
generators, and the EPA-EIA unit crosswalk.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's
name. Apache-2.0.
"""
import argparse
import csv
import datetime as dt
import hashlib
import importlib
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import truth_core as tc  # noqa: E402

import numpy as np  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

REPO_RAW = "https://raw.githubusercontent.com/munimtechnologies/cold-outages/main/"
OUTAGE_FILES = {  # git blob sha1 of the pre-registered outage-1 files (logged, checked)
    "outage/outage_core.py": "7e33ee549355cf284134d362a9dd712bd2a6e28a",
    "outage/outage_job.py": "a69e02aa59031066e88919b72b1abe29554366bf",
    "outage/test_outage_core.py": "7add43045209dd10aaf1c64ca1952d08660f1d5c",
}
ERCOT_URL = "https://www.ercot.com/files/docs/2021/03/12/Unit_Outage_Data_20210312.xlsx"
UA = "mv2-truth-1/0.1 (MV2 of Munim, Inc.; mv2@munimtech.com)"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def http_get(url):
    last = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 ** attempt)
    raise last


def blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def load_outage(work):
    d = os.path.join(work, "outage1")
    os.makedirs(d, exist_ok=True)
    shas = {}
    for path, want in OUTAGE_FILES.items():
        data = http_get(REPO_RAW + path)
        got = blob_sha(data)
        shas[path] = {"expected": want, "got": got, "match": got == want}
        log("outage-1 file", path, "sha", got, "MATCH" if got == want else "DIFFERS FROM EXPECTED")
        with open(os.path.join(d, os.path.basename(path)), "wb") as fh:
            fh.write(data)
    t = subprocess.run([sys.executable, os.path.join(d, "test_outage_core.py")], capture_output=True, text=True)
    sys.stdout.write(t.stdout[-3000:])
    sys.stdout.write(t.stderr[-3000:])
    if t.returncode != 0:
        sys.exit("outage_core tests failed")
    sys.path.insert(0, d)
    oc = importlib.import_module("outage_core")
    oj = importlib.import_module("outage_job")
    oj.UA["User-Agent"] = UA
    return oc, oj, shas


def read_counties(path):
    """plant_id_eia -> county from PUDL's plant entity table."""
    names = set(pq.read_schema(path).names)
    if "county" not in names:
        log("no county column in", path, "columns:", sorted(names))
        return {}
    t = pq.read_table(path, columns=["plant_id_eia", "county"])
    out = {}
    for r in t.to_pylist():
        if r["plant_id_eia"] is not None and r["county"]:
            out[r["plant_id_eia"]] = str(r["county"])
    log("plants with county:", len(out))
    return out


def ratio(k_n):
    k, n = k_n
    return None if n == 0 else round(k / n, 4)


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
    oc, oj, shas = load_outage("/tmp/truth1")
    if a.wait_for and not oj.wait_for(a.wait_for, a.token, a.minutes):
        sys.exit("plan not live")

    # ---- ERCOT's official list
    cache = os.path.join(a.data_dir, "ercot_Unit_Outage_Data_20210312.xlsx")
    if os.path.exists(cache) and os.path.getsize(cache) > 0:
        with open(cache, "rb") as fh:
            raw = fh.read()
    else:
        raw = http_get(ERCOT_URL)
        with open(cache, "wb") as fh:
            fh.write(raw)
    ercot_sha256 = hashlib.sha256(raw).hexdigest()
    log("ERCOT file bytes", len(raw), "sha256", ercot_sha256)
    sheets, d1904 = tc.read_xlsx(raw)
    for name, rows in sheets:
        log("sheet", name, "rows", len(rows))
        for row in rows[:8]:
            log("  ", row[:14])
    recs, info = tc.parse_records(sheets, d1904)
    log("layout:", json.dumps(info, default=str))
    if not recs:
        sys.exit("no ERCOT records parsed; see the sheet dump above")
    fuels = {}
    for r in recs:
        fuels[(r["fuel"], r["fuel_group"])] = fuels.get((r["fuel"], r["fuel_group"]), 0) + 1
    log("ERCOT fuel values:", sorted(fuels.items(), key=lambda kv: -kv[1]))
    for r in recs[:5]:
        log("  record", {k: r[k] for k in ("station", "unit", "county_n", "fuel", "seasonal_mw", "available_mw",
                                          "reduction_mw", "start_utc", "end_utc")})

    # ---- PUDL tables and CEMS
    gpath = oj.download("core_eia860__scd_generators.parquet", a.data_dir)
    ppath = oj.download("core_eia860__scd_plants.parquet", a.data_dir)
    spath = oj.download("core_epa__assn_eia_epacamd_subplant_ids.parquet", a.data_dir)
    epath = oj.download("core_eia__entity_plants.parquet", a.data_dir)
    names = oj.read_names(epath)
    counties = read_counties(epath)
    ba_rows = oj.read_ba_rows(ppath)
    fuel = oj.read_fuel(gpath, spath)

    f, pf, years_of_group, cov = oj.cems_open(oj.BASE + "core_epacems__hourly_emissions.parquet")
    lb = oc.LOOKBACK_DAYS * 24
    s0, s1 = tc.COVER
    h0 = oj.ehour(s0) - lb
    ws = lb
    we = ws + (oj.ehour(s1) - oj.ehour(s0))
    window = {"h0": h0, "n": we + oc.TAIL_HOURS}
    store = oj.Store([window])
    oj.read_cems(pf, f, years_of_group, [window], store)

    # ---- trips of ERCOT units (outage-1 rule)
    arr = store.arr[0]
    p_off = oj.ehour(tc.PRIMARY[0]) - oj.ehour(s0)
    p_len = oj.ehour(tc.PRIMARY[1]) - oj.ehour(tc.PRIMARY[0])
    cems_curve = [0.0] * (we - ws)
    trips, units = [], []
    n_ercot_units = n_no_county = 0
    active = np.nonzero(arr[:, max(0, ws - 3):we].max(axis=1) > 0)[0]
    for g in active.tolist():
        plant, unit = store.units[g]
        state = store.state[g] or ""
        ba = oc.ba_for_year(ba_rows.get(plant, []), 2021)
        if not oc.in_area("ERCOT", ba, state):
            continue
        loads = arr[g].tolist()
        cap = oc.unit_cap(loads, we)
        if cap < oc.MIN_CAP_MW:
            continue
        n_ercot_units += 1
        county = counties.get(plant, "")
        cn = tc.norm_county(county)
        if not cn:
            n_no_county += 1
        run = oc.RUN_FRAC * cap
        hard = set()
        for k in range(max(1, ws - tc.RUN_BEFORE_H - 2), we):
            if loads[k - 1] >= run and loads[k] >= run:
                hard.add(h0 + k)
        units.append({"county_n": cn, "cap": cap, "hard": hard})
        found, contrib = oc.detect(loads, ws, we, cap)
        for k, v in enumerate(contrib):
            cems_curve[k] += v
        fc = fuel.get((plant, unit), "UNKNOWN")
        for (i, j) in found:
            trips.append({"plant_id_eia": plant, "plant_name": names.get(plant, ""), "unit": unit,
                          "county": county, "county_n": cn, "fuel": fc, "cap": cap,
                          "start_utc": oj.from_ehour(h0 + i),
                          "back_utc": None if j is None else oj.from_ehour(h0 + j)})
    log("ERCOT CEMS units", n_ercot_units, "without county", n_no_county, "trips", len(trips))

    # ---- scores
    prec = tc.precision(trips, recs)
    plc = tc.placebo_precision(trips, recs)
    rec = tc.recall(recs, units, trips)
    curve_c = cems_curve[p_off:p_off + p_len]
    curve_e = tc.ercot_curve(recs, oj.ehour(tc.PRIMARY[0]), p_len)
    r = tc.pearson(curve_c, curve_e)
    preds = tc.score(prec, plc, rec, r)
    log("precision", prec, "placebo", plc, "recall", rec, "pearson", r, "predictions", preds)

    variants = {
        "precision_tol_1h": tc.precision(trips, recs, tol_h=1.0),
        "precision_tol_6h": tc.precision(trips, recs, tol_h=6.0),
        "precision_no_size_check": tc.precision(trips, recs, check_cap=False),
        "placebo_minus_24h": tc.precision(trips, recs, shift_h=-24.0),
        "placebo_plus_24h": tc.precision(trips, recs, shift_h=24.0),
        "recall_tol_1h": tc.recall(recs, units, trips, tol_h=1.0),
        "recall_tol_6h": tc.recall(recs, units, trips, tol_h=6.0),
        "recall_no_size_check": tc.recall(recs, units, trips, check_cap=False),
        "precision_feb10_to_14": tc.precision(trips, recs, window=(tc.COVER[0], tc.PRIMARY[0])),
    }
    by_fuel = {}
    for fc in ("GAS", "COAL", "OIL", "OTHER", "UNKNOWN"):
        sub = [t for t in trips if t["fuel"] == fc]
        if sub:
            by_fuel[fc] = {"precision": tc.precision(sub, recs), "placebo": tc.placebo_precision(sub, recs)}

    # ---- unit-level table: each trip in the primary window and its closest ERCOT record
    rows_out = []
    confirmed_mw = 0.0
    for t in trips:
        inwin = tc.PRIMARY[0] <= t["start_utc"] < tc.PRIMARY[1]
        m = tc.matches(t, recs) if t["county_n"] else []
        best = min(m, key=lambda i: abs((recs[i]["start_utc"] - t["start_utc"]).total_seconds())) if m else None
        if inwin and best is not None:
            confirmed_mw += t["cap"]
        rb = recs[best] if best is not None else {}
        rows_out.append({
            "plant_id_eia": t["plant_id_eia"], "plant_name": t["plant_name"], "unit": t["unit"],
            "county": t["county"], "fuel": t["fuel"], "cap_mw": round(t["cap"], 1),
            "trip_start_utc": t["start_utc"].isoformat(),
            "back_utc": "" if t["back_utc"] is None else t["back_utc"].isoformat(),
            "in_primary_window": inwin, "ercot_confirmed": best is not None,
            "ercot_station": rb.get("station", ""), "ercot_unit": rb.get("unit", ""),
            "ercot_fuel": rb.get("fuel", ""), "ercot_seasonal_mw": rb.get("seasonal_mw", ""),
            "ercot_reduction_mw": rb.get("reduction_mw", ""),
            "ercot_start_utc": rb["start_utc"].isoformat() if rb else "",
            "minutes_ercot_minus_cems": round((rb["start_utc"] - t["start_utc"]).total_seconds() / 60.0) if rb else ""})
    gaps = sorted(abs(x["minutes_ercot_minus_cems"]) for x in rows_out
                  if x["ercot_confirmed"] and x["in_primary_window"])
    med_gap = None
    if gaps:
        med_gap = gaps[len(gaps) // 2] if len(gaps) % 2 else (gaps[len(gaps) // 2 - 1] + gaps[len(gaps) // 2]) / 2.0

    n_red = sum(1 for x in recs if x["redacted"])
    n_fossil = sum(1 for x in recs if x["fossil"] and not x["redacted"])
    n_fossil_full = sum(1 for x in recs if x["fossil"] and not x["redacted"] and x["full"] is True
                        and tc.PRIMARY[0] <= x["start_utc"] < tc.PRIMARY[1])
    out = {
        "preregistration": "truth-1", "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "outage1_files": shas, "ercot_file": {"url": ERCOT_URL, "sha256": ercot_sha256, "bytes": len(raw),
                                              "layout": info},
        "cems_coverage_end_exclusive": (cov + oc.HOUR).isoformat() if cov else None,
        "ercot_records": len(recs), "ercot_redacted": n_red, "ercot_fossil_named": n_fossil,
        "ercot_fossil_full_outages_primary": n_fossil_full,
        "cems_ercot_units": n_ercot_units, "cems_units_without_county": n_no_county,
        "cems_trips_feb10_20": len(trips),
        "precision": {"confirmed": prec[0], "trips": prec[1], "share": ratio(prec)},
        "placebo": {"confirmed": plc[0], "trips": plc[1], "share": ratio(plc)},
        "recall": {"found": rec[0], "eligible": rec[1], "share": ratio(rec)},
        "pearson_hourly": r,
        "peak_mw": {"cems_trips": max(curve_c) if curve_c else None, "ercot_fossil": max(curve_e) if curve_e else None},
        "confirmed_trip_capacity_mw": round(confirmed_mw, 1),
        "median_abs_minutes_ercot_minus_cems": med_gap,
        "variants": {k: {"k": v[0], "n": v[1], "share": ratio(v)} for k, v in variants.items()},
        "by_fuel": {k: {kk: {"k": vv[0], "n": vv[1], "share": ratio(vv)} for kk, vv in v.items()}
                    for k, v in by_fuel.items()},
        "predictions": preds,
    }
    with open(os.path.join(a.out_dir, "truth1.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)

    fields = list(rows_out[0].keys()) if rows_out else ["plant_id_eia"]
    with open(os.path.join(a.out_dir, "truth1_trips.csv"), "w", encoding="utf-8", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=fields)
        wtr.writeheader()
        for row in sorted(rows_out, key=lambda x: x["trip_start_utc"]):
            wtr.writerow(row)

    with open(os.path.join(a.out_dir, "truth1_curves.csv"), "w", encoding="utf-8", newline="") as fh:
        wtr = csv.writer(fh)
        wtr.writerow(["hour_utc", "cems_trip_mw", "ercot_fossil_outage_mw"])
        for k in range(p_len):
            wtr.writerow([oj.from_ehour(oj.ehour(tc.PRIMARY[0]) + k).isoformat(), round(curve_c[k], 1),
                          round(curve_e[k], 1)])

    rfields = ["sheet", "row", "station_code", "station", "unit", "county", "fuel", "fuel_group", "seasonal_mw",
               "available_mw", "reduction_mw", "full", "start_utc", "end_utc", "redacted"]
    with open(os.path.join(a.out_dir, "truth1_ercot_records.csv"), "w", encoding="utf-8", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=rfields)
        wtr.writeheader()
        for x in recs:
            wtr.writerow({k: (x[k].isoformat() if isinstance(x.get(k), dt.datetime) else x.get(k, ""))
                          for k in rfields})

    word = {True: "held", False: "failed", None: "not scorable"}
    lines = ["# truth-1 results (machine-written)", "",
             "ERCOT records: %d (%d redacted, %d fossil with a county). CEMS ERCOT units: %d; trips Feb 10-20: %d."
             % (len(recs), n_red, n_fossil, n_ercot_units, len(trips)), "",
             "| measure | value |", "|---|---|",
             "| precision (CEMS trips Feb 14-19 confirmed by ERCOT) | %d / %d = %s |" % (prec[0], prec[1], ratio(prec)),
             "| placebo precision (+/-24 h) | %d / %d = %s |" % (plc[0], plc[1], ratio(plc)),
             "| recall (eligible ERCOT full outages found) | %d / %d = %s |" % (rec[0], rec[1], ratio(rec)),
             "| Pearson r, hourly MW curves | %s |" % r,
             "| peak MW (CEMS trips / ERCOT fossil records) | %s / %s |" % (out["peak_mw"]["cems_trips"],
                                                                      out["peak_mw"]["ercot_fossil"]),
             "| median minutes between ERCOT and CEMS starts | %s |" % med_gap, "",
             "Variants: %s" % json.dumps(out["variants"]), "",
             "By fuel: %s" % json.dumps(out["by_fuel"]), "",
             "Predictions: " + ", ".join("%s=%s" % (k, word[v]) for k, v in preds.items())]
    with open(os.path.join(a.out_dir, "truth1.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
