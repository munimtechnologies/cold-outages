# cold-outages

**Which power plants fail when the U.S. grid freezes, as seen in public data.**

In every big cold snap (Uri 2021, Elliott 2022, January 2025, Fern 2026), tens of gigawatts of power
plants fail at the worst moment. The official record of *which* units failed is NERC's GADS database, and
it is confidential. The public gets totals.

This project tests whether EPA's public hourly emissions data (CEMS) can rebuild those failures unit by
unit. A fossil unit that runs hard, drops to zero within an hour and stays off has the signature of a
trip.

**Stage 1, outage-1:** one fixed rule applied to seven cold events from 2011 to 2026, checked against the
official FERC/NERC totals and against the same calendar weeks in ordinary years.

- Plan, pre-registered before any hourly data was read: [docs/outage-plan.md](docs/outage-plan.md)
  (five predictions with probabilities, definitions and known limits)
- Code: [outage/outage_core.py](outage/outage_core.py) (standard library; tests in
  `outage/test_outage_core.py`) and [outage/outage_job.py](outage/outage_job.py) (data job)
- Results: `docs/outage.md`, once the job has run.

**Check of stage 1, truth-1:** are the trips real? During Winter Storm Uri, Texas regulators made ERCOT
publish every generator outage and derate, unit by unit. That list is the only public answer key. truth-1
measures what share of the trips the stage-1 rule finds in Texas appear in ERCOT's list, and what share of
ERCOT's full outages the rule finds, against a time-shifted placebo.

- Plan, pre-registered before any CEMS data was read and before ERCOT's file was parsed:
  [docs/truth-plan.md](docs/truth-plan.md) (four predictions with probabilities)
- Code: [outage/truth_core.py](outage/truth_core.py) (standard library; tests in
  `outage/test_truth_core.py`) and [outage/truth_job.py](outage/truth_job.py). The job reuses the
  stage-1 trip rule unchanged.
- Results: `docs/truth.md`.

**Stage 2, temp-1:** how much more often do coal and gas units trip in the cold? This asks for the
hourly trip hazard of every CEMS unit from 2016 to 2025 by the air temperature at the nearest NOAA
station. So far this temperature dependence has been measured only from confidential GADS data (Murphy,
Sowell and Apt, 2019).

- Plan, pre-registered before any hourly data was read: [docs/temp-plan.md](docs/temp-plan.md)
  (seven predictions with probabilities, a placebo-temperature control and a no-named-storms check)
- Core definitions: [outage/temp_core.py](outage/temp_core.py) (numpy; tests in
  `outage/test_temp_core.py`). Data job: [outage/temp_job.py](outage/temp_job.py), with the choices the
  plan left open fixed in advance in [docs/temp-job.md](docs/temp-job.md).
- Results: `docs/temp.md`.

**Stage 3, repeat-1:** do the same units fail storm after storm, and did that change after NERC's
cold-weather standard EOP-012 took effect on 1 October 2024? For units that ran hard in two cold events,
this compares the chance of tripping in the second event for units that tripped in the first against
units that did not. The comparison is stratified by state, set against ordinary winter weeks, and made
before the standard (Uri to Elliott) and after it (Elliott to January 2025 and the Winter 2026 storms).

- Plan, pre-registered before any hourly data was read: [docs/repeat-plan.md](docs/repeat-plan.md)
  (five predictions with probabilities)
- Code: [outage/repeat_core.py](outage/repeat_core.py) (standard library; tests in
  `outage/test_repeat_core.py`) and [outage/repeat_job.py](outage/repeat_job.py). The job reuses the
  stage-1 trip rule unchanged.
- Results: `docs/repeat.md`.

Every prediction will be reported as held, failed or not scorable.

Data: Catalyst Cooperative's [PUDL](https://catalyst.coop/pudl/) build of EPA CEMS and EIA-860 (CC BY 4.0);
NOAA ISD-Lite station temperatures (AWS Open Data); ERCOT's public February 2021 unit outage file.

Run the tests: `python outage/test_outage_core.py`, `python outage/test_truth_core.py`,
`python outage/test_repeat_core.py` and `python outage/test_temp_core.py` (needs `numpy`).
Run the stage-1 job (needs `pyarrow`, `numpy` and internet):
`python outage/outage_job.py --data-dir data --out-dir out`.

Part of MV2's open research on grid reliability. See also
[doe-202c-orders](https://github.com/munimtechnologies/doe-202c-orders), which tests whether the plants
DOE keeps open under emergency orders show up when the grid is tightest.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0;
text and data CC BY 4.0.
