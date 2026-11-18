# SPDX-License-Identifier: Apache-2.0
"""repeat-1 job: do the fossil units that trip in one U.S. cold event trip
again in the next, and did that persistence change after NERC's cold-weather
standard EOP-012 took effect (1 October 2024)? Plan: docs/repeat-plan.md
(Pre-registration id: repeat-1), written before any hourly data was read.

Trips, "ran hard", capability, areas and event windows are the outage-1
definitions. This job downloads outage/outage_core.py, outage/outage_job.py
and outage/test_outage_core.py from the public repository, logs their git
blob shas, runs the outage-1 tests, and only then reads data.

Data (all public, no key): Catalyst Cooperative's PUDL nightly build (CC BY
4.0) of EPA CEMS hourly emissions, EIA-860 plants and generators, and the
EPA-EIA unit crosswalk.

MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's
name. Apache-2.0.
"""
import argparse
import csv
import datetime as dt
import hashlib
import importlib
import json
import math
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repeat_core as rc  # noqa: E402

import numpy as np  # noqa: E402

REPO_RAW = "https://raw.githubusercontent.com/munimtechnologies/cold-outages/main/"
OUTAGE_FILES = {  # git blob sha1 of the pre-registered outage-1 files (logged, checked)
    "outage/outage_core.py": "7e33ee549355cf284134d362a9dd712bd2a6e28a",
    "outage/outage_job.py": "a69e02aa59031066e88919b72b1abe29554366bf",
    "outage/test_outage_core.py": "7add43045209dd10aaf1c64ca1952d08660f1d5c",
}
UA = "mv2-repeat-1/0.1 (MV2 of Munim, Inc.; mv2@munimtech.com)"
POOLS = ("PRE", "POST", "EVENT", "PLACEBO")


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


def overlaps(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


def fnum(x):
    if x is None:
        return None
    if isinstance(x, float) and math.isinf(x):
        return "inf"
    return round(x, 4) if isinstance(x, float) else x


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
    oc, oj, shas = load_outage("/tmp/repeat1")
    if a.wait_for and not oj.wait_for(a.wait_for, a.token, a.minutes):
        sys.exit("plan not live")

    gpath = oj.download("core_eia860__scd_generators.parquet", a.data_dir)
    ppath = oj.download("core_eia860__scd_plants.parquet", a.data_dir)
    spath = oj.download("core_epa__assn_eia_epacamd_subplant_ids.parquet", a.data_dir)
    try:
        names = oj.read_names(oj.download("core_eia__entity_plants.parquet", a.data_dir))
    except Exception as e:  # noqa: BLE001
        log("entity_plants download failed:", e)
        names = {}
    ba_rows = oj.read_ba_rows(ppath)
    fuel = oj.read_fuel(gpath, spath)

    f, pf, years_of_group, cov = oj.cems_open(oj.BASE + "core_epacems__hourly_emissions.parquet")
    if cov is None:
        sys.exit("no CEMS coverage")
    coverage_end = cov + oc.HOUR

    # ---- windows: each event and its two outage-1 control windows
    lb = oc.LOOKBACK_DAYS * 24
    windows = []
    for ev in oc.EVENTS:
        spans = []
        if ev["end"] + oc.TAIL_HOURS * oc.HOUR <= coverage_end:
            spans.append(("event", ev["id"], ev["start"], ev["end"]))
        for ci, (s0, s1) in enumerate(oc.control_windows(ev, oc.EVENTS, coverage_end)):
            spans.append(("control", "%s~c%d" % (ev["id"], ci + 1), s0, s1))
        for kind, label, s0, s1 in spans:
            h0 = oj.ehour(s0) - lb
            ws = lb
            we = ws + (oj.ehour(s1) - oj.ehour(s0))
            windows.append({"event": ev, "kind": kind, "label": label, "start": s0, "end": s1, "h0": h0,
                            "ws": ws, "we": we, "n": we + oc.TAIL_HOURS})
    log("windows:", [(w["label"], w["start"].date().isoformat(), w["end"].date().isoformat()) for w in windows])
    store = oj.Store(windows)
    oj.read_cems(pf, f, years_of_group, windows, store)

    # ---- per window: units that ran hard (eligible) and whether they tripped
    flags, winfo, unit_info = {}, {}, {}
    for wi, w in enumerate(windows):
        ev = w["event"]
        year = ev["start"].year          # area membership uses the event year (as in outage-1)
        arr = store.arr[wi]
        ws, we = w["ws"], w["we"]
        fl = {}
        active = np.nonzero(arr[:, max(0, ws - 3):we].max(axis=1) > 0)[0]
        for g in active.tolist():
            plant, unit = store.units[g]
            state = store.state[g] or ""
            ba = oc.ba_for_year(ba_rows.get(plant, []), year)
            if not oc.in_area(rc.AREA, ba, state):
                continue
            loads = arr[g].tolist()
            cap = oc.unit_cap(loads, we)
            if cap < oc.MIN_CAP_MW or not oc.ran_hard(loads, ws - 3, we, cap):
                continue
            trips, _ = oc.detect(loads, ws, we, cap)
            key = "%s|%s" % (plant, unit)
            fl[key] = (plant, state, bool(trips))
            ui = unit_info.setdefault(key, {"plant_id_eia": plant, "plant_name": names.get(plant, ""),
                                            "unit": unit, "state": state, "fuel": fuel.get((plant, unit), "UNKNOWN"),
                                            "cap_mw_max": 0.0, "eligible": [], "tripped": []})
            ui["cap_mw_max"] = max(ui["cap_mw_max"], cap)
            ui["eligible"].append(w["label"])
            if trips:
                ui["tripped"].append(w["label"])
                if w["kind"] == "event":
                    ui.setdefault("first_trip_utc", {})[w["label"]] = oj.from_ehour(w["h0"] + trips[0][0]).isoformat()
        flags[w["label"]] = fl
        winfo[w["label"]] = {"kind": w["kind"], "event": ev["id"], "start": w["start"].isoformat(),
                             "end": w["end"].isoformat(), "eligible_units": len(fl),
                             "tripped_units": sum(1 for v in fl.values() if v[2])}
        log(w["label"], "eligible", len(fl), "tripped", winfo[w["label"]]["tripped_units"])

    ev_ids = [ev["id"] for ev in oc.EVENTS if ev["id"] in flags]
    controls = {ev["id"]: [w for w in windows if w["kind"] == "control" and w["event"]["id"] == ev["id"]]
                for ev in oc.EVENTS}

    def placebo_labels(A, B):
        """A's first control, and B's first control that does not overlap it."""
        if not controls[A] or not controls[B]:
            return None
        ca = controls[A][0]
        for cb in controls[B]:
            if not overlaps(ca, cb):
                return ca["label"], cb["label"]
        return None

    def fuel_of(u):
        return unit_info[u]["fuel"]

    # ---- pairs, pools, bootstrap inputs
    flaky = {u for u, ui in unit_info.items() if any("~c" in lab for lab in ui["tripped"])}
    pairs_out, pool_counts, plant_counts = {}, {p: {} for p in POOLS}, {}
    variant_counts = {p: {} for p in POOLS}
    pair_rr, pair_rr_variant = {}, {}
    pair_csv = []

    def add_pool(pool, name, rows, target, plants=True):
        for u, plant, s, ta, tb in rows:
            rc.add(target[pool], (name, s), ta, tb)
            if plants:
                v = plant_counts.setdefault(plant, {})
                rc.add(v, (pool, (name, s)), ta, tb)

    for pair in rc.ALL_PAIRS:
        A, B = pair
        name = rc.pair_name(pair)
        if A not in flags or B not in flags:
            pairs_out[name] = {"covered": False}
            continue
        rows = rc.pair_rows(flags[A], flags[B])
        cnt = rc.strata(rows, name)
        ok = rc.scorable(cnt)
        rr = rc.mh_rr(cnt)
        pair_rr[name] = (rr, ok)
        rows_v = [x for x in rows if x[0] not in flaky]
        cnt_v = rc.strata(rows_v, name)
        pair_rr_variant[name] = (rc.mh_rr(cnt_v), rc.scorable(cnt_v))
        entry = {"covered": True, "scorable": ok, "mh_rr": fnum(rr), "crude": {k: fnum(v) for k, v in rc.crude(cnt).items()},
                 "units_eligible_both": len(rows), "by_fuel": {},
                 "no_control_trip_variant": {"mh_rr": fnum(pair_rr_variant[name][0]),
                                             "scorable": pair_rr_variant[name][1], "units": len(rows_v)}}
        for fc in ("GAS", "COAL", "OIL", "OTHER", "UNKNOWN"):
            sub = [x for x in rows if fuel_of(x[0]) == fc]
            if not sub:
                continue
            c2 = rc.strata(sub, name)
            entry["by_fuel"][fc] = {"mh_rr": fnum(rc.mh_rr(c2)), "scorable": rc.scorable(c2),
                                    **{k: fnum(v) for k, v in rc.crude(c2).items()}}
            t = rc.crude(c2)
            pair_csv.append({"pair": name, "fuel": fc, "a": t["a"], "n1": t["n1"], "c": t["c"], "n0": t["n0"],
                             "crude_rr": fnum(t["crude_rr"]), "mh_rr": fnum(rc.mh_rr(c2))})
        t = rc.crude(cnt)
        pair_csv.append({"pair": name, "fuel": "ALL", "a": t["a"], "n1": t["n1"], "c": t["c"], "n0": t["n0"],
                         "crude_rr": fnum(t["crude_rr"]), "mh_rr": fnum(rr)})
        if ok:
            pool = "PRE" if pair in rc.PRE_PAIRS else "POST"
            add_pool(pool, name, rows, pool_counts)
            add_pool("EVENT", name, rows, pool_counts)
            add_pool(pool, name, rows_v, variant_counts, plants=False)
            add_pool("EVENT", name, rows_v, variant_counts, plants=False)
            pl = placebo_labels(A, B)
            entry["placebo_windows"] = pl
            if pl is not None:
                prow = rc.pair_rows(flags[pl[0]], flags[pl[1]])
                pc_ = rc.strata(prow, name)
                entry["placebo"] = {"mh_rr": fnum(rc.mh_rr(pc_)), **{k: fnum(v) for k, v in rc.crude(pc_).items()}}
                add_pool("PLACEBO", name, prow, pool_counts)
                t = rc.crude(pc_)
                pair_csv.append({"pair": name + " placebo " + "/".join(pl), "fuel": "ALL", "a": t["a"], "n1": t["n1"],
                                 "c": t["c"], "n0": t["n0"], "crude_rr": fnum(t["crude_rr"]),
                                 "mh_rr": fnum(rc.mh_rr(pc_))})
        pairs_out[name] = entry
        log(name, "units", len(rows), "MH RR", rr, "scorable", ok)

    pool_rr = {p: (rc.mh_rr(pool_counts[p]) if pool_counts[p] else None) for p in POOLS}
    pool_rr_variant = {p: (rc.mh_rr(variant_counts[p]) if variant_counts[p] else None) for p in ("PRE", "POST", "EVENT")}
    log("pooled MH RR:", pool_rr)
    reps = rc.boot(plant_counts, list(POOLS))
    boot = {p: rc.ci95(reps, p) for p in POOLS}
    ratio = [r["POST"] / r["PRE"] for r in reps
             if r.get("POST") is not None and r.get("PRE") not in (None, 0) and not math.isinf(r["PRE"])
             and not math.isinf(r["POST"])]
    post_lt_pre = sum(1 for r in reps if r.get("POST") is not None and r.get("PRE") is not None
                      and r["POST"] < r["PRE"])

    ev_flags = {e: flags[e] for e in ev_ids}
    rep_units = rc.repeaters(ev_flags) if len(ev_ids) >= rc.MIN_EVENTS_REPEATER else []
    rep_obs = len(rep_units) if len(ev_ids) >= rc.MIN_EVENTS_REPEATER else None
    rep_null = rc.perm_null(ev_flags) if rep_obs is not None else []
    preds = rc.score(pair_rr, pool_rr, rep_obs, rep_null)
    preds_variant = rc.score(pair_rr_variant, dict(pool_rr_variant, PLACEBO=None), None, [])
    log("predictions:", preds)

    out = {"preregistration": "repeat-1", "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
           "outage1_files": shas, "cems_coverage_end_exclusive": coverage_end.isoformat(),
           "events_covered": ev_ids, "windows": winfo, "pairs": pairs_out,
           "pooled_mh_rr": {k: fnum(v) for k, v in pool_rr.items()},
           "pooled_ci95_plant_bootstrap": {k: [fnum(v[0]), fnum(v[1]), v[2]] for k, v in boot.items()},
           "post_over_pre_ci95": [fnum(rc.pct(ratio, 2.5)), fnum(rc.pct(ratio, 97.5)), len(ratio)],
           "bootstrap_share_post_below_pre": (post_lt_pre / len(reps)) if reps else None,
           "repeaters_observed": rep_obs,
           "repeaters_null": {"p95": rc.pct(rep_null, 95), "median": rc.pct(rep_null, 50),
                              "max": max(rep_null) if rep_null else None,
                              "p_value": ((1 + sum(1 for x in rep_null if x >= rep_obs)) / (len(rep_null) + 1))
                              if rep_null else None},
           "predictions": preds,
           "no_control_trip_variant": {"units_excluded": len(flaky),
                                       "pooled_mh_rr": {k: fnum(v) for k, v in pool_rr_variant.items()},
                                       "R1_R3": {k: preds_variant[k] for k in ("R1", "R2", "R3")}}}
    with open(os.path.join(a.out_dir, "repeat1.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)

    with open(os.path.join(a.out_dir, "repeat1_pairs.csv"), "w", encoding="utf-8", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=["pair", "fuel", "a", "n1", "c", "n0", "crude_rr", "mh_rr"])
        wtr.writeheader()
        for row in pair_csv:
            wtr.writerow(row)

    fields = ["plant_id_eia", "plant_name", "unit", "state", "fuel", "cap_mw_max", "events_eligible",
              "events_tripped", "n_events_tripped", "controls_tripped", "first_trip_utc"]
    with open(os.path.join(a.out_dir, "repeat1_units.csv"), "w", encoding="utf-8", newline="") as fh:
        wtr = csv.DictWriter(fh, fieldnames=fields)
        wtr.writeheader()
        for key in sorted(unit_info, key=lambda k: (-sum(1 for x in unit_info[k]["tripped"] if "~c" not in x), k)):
            ui = unit_info[key]
            evt = [x for x in ui["tripped"] if "~c" not in x]
            wtr.writerow({"plant_id_eia": ui["plant_id_eia"], "plant_name": ui["plant_name"], "unit": ui["unit"],
                          "state": ui["state"], "fuel": ui["fuel"], "cap_mw_max": round(ui["cap_mw_max"], 1),
                          "events_eligible": " ".join(x for x in ui["eligible"] if "~c" not in x),
                          "events_tripped": " ".join(evt), "n_events_tripped": len(evt),
                          "controls_tripped": " ".join(x for x in ui["tripped"] if "~c" in x),
                          "first_trip_utc": " ".join("%s=%s" % kv for kv in sorted(ui.get("first_trip_utc", {}).items()))})

    word = {True: "held", False: "failed", None: "not scorable"}
    lines = ["# repeat-1 results (machine-written)", "",
             "CEMS through %s (exclusive). Events covered: %s." % (coverage_end.isoformat(), ", ".join(ev_ids)), "",
             "| pair | units eligible in both | tripped in A (n1) | of them tripped in B | others tripped in B | "
             "crude RR | MH RR (by state) | scorable | placebo MH RR |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, e in pairs_out.items():
        if not e.get("covered"):
            lines.append("| %s | not in coverage | | | | | | | |" % name)
            continue
        c = e["crude"]
        lines.append("| %s | %d | %s | %s | %s/%s | %s | %s | %s | %s |" % (
            name, e["units_eligible_both"], c["n1"], c["a"], c["c"], c["n0"], c["crude_rr"], e["mh_rr"],
            e["scorable"], (e.get("placebo") or {}).get("mh_rr")))
    lines += ["", "Pooled MH RR (plant-bootstrap 95%% CI): %s" % "; ".join(
        "%s %s %s" % (p, fnum(pool_rr[p]), boot[p][:2]) for p in POOLS),
        "POST/PRE ratio 95%% CI: %s; share of replicates with POST < PRE: %s" % (
            out["post_over_pre_ci95"][:2], out["bootstrap_share_post_below_pre"]),
        "Repeaters (tripped in >= %d events): %s; permutation null p95 %s, p-value %s" % (
            rc.MIN_EVENTS_REPEATER, rep_obs, out["repeaters_null"]["p95"], out["repeaters_null"]["p_value"]),
        "", "Predictions: " + ", ".join("%s=%s" % (k, word[v]) for k, v in preds.items()),
        "Variant without units that tripped in any control window (%d excluded): pooled %s; %s" % (
            len(flaky), out["no_control_trip_variant"]["pooled_mh_rr"],
            ", ".join("%s=%s" % (k, word[v]) for k, v in out["no_control_trip_variant"]["R1_R3"].items()))]
    with open(os.path.join(a.out_dir, "repeat1.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
