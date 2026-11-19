# truth-1: are the trips we see in EPA's public data real? A unit-level check against ERCOT's Uri outage list

Pre-registration id: truth-1.

Written 2026-11-19, before any EPA CEMS hourly data was read for this project and before ERCOT's
outage file was parsed. By MV2 of Munim, Inc. (mv2@munimtech.com). Made with AI agents working in MV2's
name; no human expert has reviewed this plan. Text CC BY 4.0, code Apache-2.0.

## Why this check

Stage 1 of this project (outage-1, [outage-plan.md](outage-plan.md)) rebuilds fossil-unit trips in U.S.
cold events from EPA's public hourly gross-load data (CEMS): a unit that ran at 60% or more of its
capability, then sat at 2% or less for six hours, counts as a trip. Its predictions compare event-wide
totals with the official FERC/NERC numbers, so with seven events they can only show that totals move
together. They cannot show that the units it names actually failed.

There is one public unit-level answer key. After Winter Storm Uri, the Public Utility Commission of Texas
ordered ERCOT to publish every outage and derate of an ERCOT generation resource that began between
10 and 19 February 2021: station, unit, seasonal maximum MW, MW still available, MW reduction, fuel, start
and end time, county and owner. The file is
[Unit_Outage_Data_20210312.xlsx](https://www.ercot.com/files/docs/2021/03/12/Unit_Outage_Data_20210312.xlsx)
(listed on ERCOT's [February 2021 event page](https://www.ercot.com/news/february2021)). For the event as a
whole the official record of which units failed (NERC GADS) stays confidential. truth-1 measures how many
of the trips the outage-1 rule finds in Texas during Uri appear in ERCOT's list, and how many of ERCOT's
full outages the rule finds.

If precision is high, outage-1's unit lists for Elliott, January 2025 and Winter 2026, where no public
answer key exists, become credible. That would make them the first public unit-by-unit record of which
fossil units failed in those events. If it is low, that is worth knowing before anyone uses them.

## What we looked at before writing this

- ERCOT's event page and two secondary descriptions of the file's columns. One, a search-result summary,
  quoted a sample row, an
  NG unit in Dallas County with seasonal max 568 MW, 200 MW available and a 368 MW reduction, starting
  2/14/21 11:30 AM. The file was downloaded once (193 KB, two worksheets) but could not be parsed in that
  environment, so no rows have been read. Column names in the code are found by keyword. A fixed column
  order, taken from those descriptions, is used only if no header row is found, and the job logs which of
  the two it used.
- No CEMS data. The trip rule is outage-1's, unchanged (pinned files and git blob shas below).

## Data

- ERCOT's file above. Times are Central; February 2021 was Central Standard Time (UTC-6). ERCOT's caveats
  apply: entries are self-reported by owners into its Outage Scheduler; outages shorter than two hours did
  not have to be entered; units already out before the period are not listed.
- EPA CEMS hourly gross load, EIA-860 plants and generators, plant county and the EPA-EIA crosswalk, from
  Catalyst Cooperative's PUDL nightly build (CC BY 4.0).

## Definitions (fixed now)

- **ERCOT units:** CEMS units whose plant is in balancing authority ERCO in EIA-860 for 2021 (or, with no
  BA, in Texas), with capability of at least 25 MW (outage-1's `in_area("ERCOT")`, `unit_cap`).
- **Trips:** outage-1's `detect` on hours from 2021-02-10 06:00 UTC to 2021-02-20 06:00 UTC (midnight
  to midnight Central, 10-19 February), with outage-1's 30-day look-back and 6-hour tail.
- **Primary window:** trips and records starting 2021-02-14 06:00 to 2021-02-20 06:00 UTC (14-19 February,
  Central time), the core of the event.
- **ERCOT fossil record:** a record whose fuel text, split into words, contains a coal word (COAL, LIG,
  SUB, BIT, CLLIG...), a gas word (NG, GAS, CC, CCGT, GT, CT, SCGT, SCLE, GSREH, GSNONR, GSSUP...) or an
  oil word (OIL, DFO, DIESEL...), and no non-fossil word (NUC, WIND, SOLAR, HYDRO, PWRSTR, STORAGE,
  BIOMASS, LANDFILL...). A record with no county is **redacted** and is never matched.
- **Match:** a trip matches a record if both are in the same county (letters only, the word COUNTY
  dropped), the record is fossil, the record's start is within 3 hours of the trip's first "off" hour, and
  the record's unit size (seasonal max, else MW reduction) is 0.25 to 4 times the CEMS unit's capability.
  The loose size range allows for combined-cycle trains, where CEMS reports each turbine and ERCOT may list
  the train.
- **Precision:** among trips in the primary window at plants with a known county, the share that match a
  record.
- **Placebo precision:** the same matching with each trip's time moved 24 hours earlier and, separately,
  24 hours later, pooled over both shifts. Only shifted times inside 10-19 February count. This measures
  how often a trip matches by chance in a county where many units were failing.
- **Recall:** among ERCOT fossil records in the primary window that are full outages (MW available at
  most 2% of seasonal max) of at least 25 MW, keep those **eligible** for CEMS: some CEMS unit in the same
  county, of fitting size, ran hard (60% of capability in two consecutive hours) in one of the 6 hours
  before the record's start hour. Recall is the share of eligible records with a trip of fitting size in
  the same county starting within 3 hours.
- **Hourly curves:** for each hour of the primary window, the MW lost to CEMS trips in ERCOT (outage-1's
  per-hour contribution, capability minus load) and the MW reduction of ERCOT fossil records in effect at
  the middle of the hour.

## Predictions (probabilities are our honest guesses now)

| id | prediction | scorable when | P(holds) |
|---|---|---|---|
| V1 | Precision is at least 0.70 | at least 30 trips | 0.60 |
| V2 | Recall is at least 0.50 | at least 20 eligible records | 0.50 |
| V3 | Precision is at least twice the placebo precision (or placebo is 0 and precision above 0) | V1 scorable | 0.75 |
| V4 | Pearson r of the two hourly curves is at least 0.80 | both curves vary | 0.55 |

Each is reported as held, failed or not scorable, whatever the result.

Reported without a prediction: the counts behind each share; precision and recall with 1-hour and 6-hour
tolerance and with no size check; the two placebo shifts separately; precision for 10-13 February;
precision by CEMS fuel (gas, coal); the peak MW of each curve; the capability of confirmed trips; the median
minutes between ERCOT's start and the CEMS trip; the number of redacted records; and the full list of trips
with the ERCOT record each matched (station, unit, fuel, MW, start).

## Known limits

- **One event, one region.** Uri in ERCOT is the only event with a public unit-level list. A good score
  here does not prove the rule works as well in PJM or MISO during Elliott.
- **Matching without a unit crosswalk.** There is no public ERCOT-to-EIA unit crosswalk, so matching uses
  county, time and size. In counties with many similar units a trip can match the wrong unit. The placebo
  measures how often that happens by chance.
- **What each source can see.** CEMS cannot see failures to start or derates (a unit that never ran, or
  dropped only part way), so recall is limited to units that were demonstrably running. ERCOT's list
  misses outages under two hours and anything owners did not enter. Gross (CEMS) and net (ERCOT) MW
  differ.
- **Counties.** EIA-860 and ERCOT may name a county differently (for example DeWitt and De Witt), which
  normalisation handles, or may place a plant in a neighbouring county, which it does not.

## How it runs

`outage/truth_core.py` (standard library; hand-checked tests in `outage/test_truth_core.py`) and
`outage/truth_job.py`. The job downloads outage-1's files from this repository, logs their git blob shas
(expected `outage_core.py` 7e33ee54..., `outage_job.py` a69e02aa..., `test_outage_core.py` 7add4304...),
and runs their tests. It then waits until this plan is public, and only then reads ERCOT's file and CEMS.
It logs the sheets, the column layout it found and the distinct fuel values. Results go to
`docs/truth.md` with `data/truth1_trips.csv`, `data/truth1_curves.csv` and the parsed ERCOT records.
If the job fails on a code or layout error, the fix is made in the open, listed in `docs/truth.md`, and
the definitions above stay unchanged.

## Prior work

Studies of Uri's generator outages use ERCOT's list itself (ERCOT's cause reports; UT Austin's July 2021
timeline, which found 96 of 585 ERCOT units with outages in February 2021 also had problems in 2011; the
Baker Institute's 2022 working paper) or confidential GADS data (the FERC-NERC report). We found no
published check of CEMS-derived trips against ERCOT's unit list, or against any official unit-level
outage record.
