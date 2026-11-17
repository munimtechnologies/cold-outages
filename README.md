# cold-outages

**Which power plants fail when the U.S. grid freezes, as seen in public data.**

In every big cold snap (Uri 2021, Elliott 2022, January 2025, Fern 2026), tens of gigawatts of power
plants fail at the worst moment. The official record of *which* units failed is NERC's GADS database, and
it is confidential. The public gets totals.

This project tests whether EPA's public hourly emissions data (CEMS) can rebuild those failures unit by
unit. A fossil unit that runs hard, drops to zero within an hour and stays off has the signature of a
trip. The first study, **outage-1**, applies one fixed rule to seven cold events from 2011 to 2026. It
checks the result against the official FERC/NERC totals and against the same calendar weeks in ordinary
years.

- Plan, pre-registered before any hourly data was read: [docs/outage-plan.md](docs/outage-plan.md)
  (five predictions with probabilities, definitions and known limits)
- Code: [outage/outage_core.py](outage/outage_core.py) (standard library; tests in
  `outage/test_outage_core.py`) and [outage/outage_job.py](outage/outage_job.py) (data job)
- Results: `docs/outage.md`, once the job has run. Every prediction will be reported as held, failed or
  not scorable.

Data: Catalyst Cooperative's [PUDL](https://catalyst.coop/pudl/) build of EPA CEMS and EIA-860 (CC BY 4.0).

Run the tests: `python outage/test_outage_core.py`. Run the job (needs `pyarrow`, `numpy` and internet):
`python outage/outage_job.py --data-dir data --out-dir out`.

Part of MV2's open research on grid reliability. See also
[doe-202c-orders](https://github.com/munimtechnologies/doe-202c-orders), which tests whether the plants
DOE keeps open under emergency orders show up when the grid is tightest.

By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's name. Code Apache-2.0;
text and data CC BY 4.0.
