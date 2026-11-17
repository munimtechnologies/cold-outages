# temp-1 data job: choices the plan left open (written before the job ran)

MV2 of Munim, Inc. (mv2@munimtech.com), 2026-11-17. Made with AI agents working in MV2's name.
Text CC BY 4.0, code Apache-2.0.

The plan (`docs/temp-plan.md`, Pre-registration id: temp-1) is unchanged. The job that applies it is
`outage/temp_job.py`. It downloads `outage/temp_core.py` and `outage/test_temp_core.py` from this
repository, logs their git blob hashes, runs the tests and stops if any fails, so the definitions
used are the pre-registered ones. No hourly data had been read for temp-1 when these notes were
written. Where the plan was silent, the job does the following:

1. **"Active from 2016 to at least 2024"** for a weather station means BEGIN on or before 2016-01-01
   and END on or after 2024-01-01 in NOAA's `isd-history.csv`, country code US, with a nonzero
   position.
2. **Hours with no CEMS row** count as zero load, the same convention as outage-1. Because units that
   report only in the ozone season (May-September) would then show a "trip" when their reporting
   stops, the job also reports (a) how many primary trips have no reported row in their off hours and
   (b) a secondary rule "reported", where only hours with a CEMS row count (reported, not scored).
3. **CEMS coverage end:** hours after the last hour in the CEMS file are not used, so the end of the
   data is not mistaken for a mass trip.
4. **Units with no generator in the EPA-EIA crosswalk** get class OTHER (`unit_class` of an empty list).
5. **Placebo temperature for 2016** uses the station's 2015 ISD-Lite file. If the previous year's file
   is missing, those hours have no placebo temperature and drop out of the placebo counts only.
6. **Station per year:** the station is chosen separately in each year (the first of the three
   nearest that has at least 2,000 hourly temperatures that year), as the plan says; the placebo uses
   the same station's previous-year file.
7. **Outputs:** `temp1.json` (scored ratios with 95% week-block bootstrap intervals, H1-H7, hazard
   curves by class and rule, diagnostics per year), `temp1_units.csv` (per unit: at-risk hours and
   trips, all / cold / reference) and `temp1_cold_trips.csv` (every primary-rule trip below -10 C,
   labelled only "consistent with a trip"). The write-up will be `docs/temp.md`.
