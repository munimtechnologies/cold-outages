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

**Stage 2, temp-1:** how much more often do coal and gas units trip in the cold? This asks for the
hourly trip hazard of every CEMS unit from 2016 to 2025 by the air temperature at the nearest NOAA
station. So far this temperature dependence has been measured only from confidential GADS data (Murphy,
Sowell and Apt, 2019).

- Plan, pre-registered before any hourly data was read: [docs/temp-plan.md](docs/temp-plan.md)
  (seven predictions with probabilities, a placebo-temperature control and a no-named-storms check)
- Core definitions: [outage/temp_core.py](outage/temp_core.py) (numpy; tests in
  `outage/test_temp_core.py`). The data job is not written yet.
- Results: `docs/temp.md`.

Every prediction will be reported as held, failed or not scorable.

Data: Catalyst Cooperative's [PUDL](https://catalyst.coop/pudl/) build of EPA CEMS and EIA-860 (CC BY 4.0);
NOAA ISD-Lite station temperatures (AWS Open Data).

Run the tests: `python outage/test_outage_core.py` and `python outage/test_temp_core.py` (needs `numpy`).
Run the stage-1 job (needs `pyarrow`, `numpy` and internet):
`python outage/outage_job.py --data-dir data --out-dir out`.

Part of MV2's open research on grid reliability. See also
[doe-202c-orders](https://github.com/munimtechnologies/doe-202c-orders), which tests whether the plants
DOE keeps open under emergency orders show up when the grid is tightest.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0;
text and data CC BY 4.0.
