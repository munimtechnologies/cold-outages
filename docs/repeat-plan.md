# repeat-1: do the same power plants fail storm after storm, and did the new cold-weather rules change that?

Pre-registration id: repeat-1.

Written on 2026-11-18 by AI agents working in the name of MV2 of Munim, Inc. (mv2@munimtech.com). It was
written before any hourly data for this study was read. The two earlier studies in this repository that
use the same data, outage-1 (`docs/outage-plan.md`) and temp-1 (`docs/temp-plan.md`), are queued and had
produced no results when this plan was written, so no unit-level trip list for any cold event had been
computed by us. The code is in `outage/repeat_core.py` and `outage/repeat_job.py` (Apache-2.0). This plan is
not edited after publication. Any later change goes in a dated note below it, and results go in
`docs/repeat.md`.

## Why this matters

After Winter Storm Uri (February 2021), FERC and NERC recommended winterisation of power plants. When
Winter Storm Elliott came 22 months later, their inquiry found that failure causes already seen in Uri came
back (frozen transmitters, sensing lines and other instruments were again a leading cause), and that many of
the earlier recommendations had made limited progress. NERC then made cold-weather preparedness
mandatory. EOP-011-2 took effect on 1 April 2023, and EOP-012-1 on 1 October 2024. Under EOP-012
requirement R6, a generator owner whose unit has a cold-weather reliability event (an outage, derate or
failure to start caused by freezing) must write a corrective action plan for that unit.

So there is a direct, unanswered question: **do the units that fail in one cold snap fail again in the
next, and did that persistence fall once the standard applied?** The official records that could answer it
(NERC GADS, the outage reports owners file) are confidential. FERC/NERC reports give totals and causes, not
which units failed twice. Academic work on cold-weather failures (Murphy, Sowell and Apt, *Applied Energy*
2019, and later papers) relies on GADS, which outsiders cannot inspect unit by unit. We found no public, unit-level measure of
repeat cold-weather failures, and no public test of whether EOP-012 changed them.

**The "wow" if it works:** "Fossil units that tripped in Winter Storm Elliott were X times as likely as
other units to trip again in the Winter 2026 storms, after the new standard. Before the standard, the
repeat ratio from Uri to Elliott was Y." Either answer matters. A repeat ratio that stayed high would mean
the standard had not yet reached the units that fail most. A clear drop would be the first public evidence
that it worked.

## Data (public, no key)

Exactly the outage-1 inputs: Catalyst Cooperative's PUDL nightly build (CC BY 4.0), read on the day the job
runs: `core_epacems__hourly_emissions` (EPA CEMS hourly gross load), `core_eia860__scd_plants`,
`core_eia860__scd_generators`, `core_epa__assn_eia_epacamd_subplant_ids` and `core_eia__entity_plants`.

## Definitions (fixed now)

All unit-level definitions are outage-1's, from `outage/outage_core.py` as published (git blob
7e33ee549355cf284134d362a9dd712bd2a6e28a). The job downloads that file, `outage/outage_job.py` and
`outage/test_outage_core.py` from this repository, logs their shas and runs the outage-1 tests before it reads
any data. These definitions are reused, not changed: the seven event windows (E2011, E2014, E2018, E2021
Uri, E2022 Elliott, E2025 January 2025, E2026 Fern and Gianna), each event's two control windows,
capability, the trip rule (main setting: 2 hours at >= 60% of capability, then <= 2% for 6 hours), "ran
hard", BA and area rules, and fuel class.

- **Area**: EAST_TX (Eastern Interconnection plus ERCOT) for every event and control window, with each
  plant's BA taken for the event's year. This is one fixed footprint, so that a unit can be followed from
  event to event.
- **Eligible in a window**: the unit has capability >= 25 MW and ran hard (>= 60% of capability in two
  consecutive hours) between 3 hours before the window and its end.
- **Tripped in a window**: eligible, and at least one trip starts inside the window.
- **Pair (A, B)**: the units eligible in both A and B. For each, did it trip in A, and did it trip in B?
- **Repeat risk ratio**: the risk of tripping in B for units that tripped in A, divided by the risk for
  units that did not trip in A. The scored version is the **Mantel-Haenszel risk ratio stratified by
  state** (the CEMS state of the unit). It compares units with others in the same state, which removes part
  of the effect of where each storm was coldest. The crude ratio is reported too.
- **Scorable pair**: at least 10 units tripped in A and at least 10 units tripped in B (both among the
  units eligible in both).
- **Pairs and pools (fixed now)**:
  - PRE (both events before EOP-012): E2014>E2018, E2018>E2021, E2021>E2022.
  - POST (B after EOP-012 took effect): E2022>E2025, E2022>E2026, E2025>E2026.
  - EVENT: all six. A pool's ratio is the Mantel-Haenszel ratio over the strata (pair, state) of its
    scorable pairs.
- **Placebo**: for each scorable pair, the same calculation with A replaced by A's first control window
  and B by B's first control window that does not overlap it. These are ordinary weeks of the same
  season a year or more away from the event. The PLACEBO pool measures how much "the same units trip
  again" happens anyway. A peaking unit that is switched off fast every evening would repeat in ordinary
  weeks too. That is why the cold-weather claim is R4, not R1 alone.
- **Repeater**: a unit that tripped in at least 3 of the covered events.
- **Permutation null for repeaters**: within each event and state, the same number of trips is dealt at
  random among the eligible units (1,000 draws, seed 20261118). Scored against the null's 95th percentile
  (nearest rank).
- **Uncertainty**: a plant-cluster bootstrap (1,000 replicates, seed 20261118) gives 95% intervals for every
  pool and for POST/PRE. Units at one plant share weather and staff, so plants are resampled whole. The
  predictions are scored on the point estimates. The intervals say how firm each one is.

## Predictions (with our probabilities, fixed now)

- **R1 (persistence after the standard)**: the Elliott>Winter 2026 (E2022>E2026) MH repeat ratio is
  >= 2.0. *p = 0.55.*
- **R2 (persistence before it)**: the Uri>Elliott (E2021>E2022) MH repeat ratio is >= 2.0. *p = 0.55.*
- **R3 (did it fall?)**: the POST pooled ratio is lower than the PRE pooled ratio. *p = 0.40.* (Our guess
  is that winterisation has not yet reached the units that fail most. The standard's freeze-protection
  deadlines run for years, and R6 plans apply only to events after 1 October 2024.)
- **R4 (cold, not habit)**: the EVENT pooled ratio is higher than the PLACEBO pooled ratio. *p = 0.60.*
- **R5 (chronic repeaters)**: the number of units that tripped in >= 3 events exceeds the 95th percentile of
  the permutation null. *p = 0.65.*

Each is scored "held", "failed" or "not scorable" by `repeat_core.score`. A prediction is not scorable when
its pair or pools are not scorable, or an event lies outside CEMS coverage on the day the job runs (if
E2026 is not covered, R1 is not scorable and POST uses only E2022>E2025). Failures are reported as plainly
as successes.

## Reported but not predicted

- Every pair's 2x2 table, crude and MH ratios, and the same by fuel (gas, coal, oil).
- E2025>E2026 on its own: the one pair in which every A-event failure falls under EOP-012's R6
  corrective-action requirement.
- A variant without the units that tripped in any control window ("habitual fast shut-downs"), with R1-R3
  recomputed.
- The list of repeaters (plant, unit, fuel, the events they tripped in, first trip hour). Every name is
  "consistent with a trip", not a confirmed forced outage.

## Known limits

- CEMS sees fossil units of 25 MW or more. The trip rule misses derates, failures to start and slow
  ramps, and cannot tell a failure from a fast deliberate shutdown. The placebo (R4) and the variant
  address the second point only in part.
- A CEMS trip is not a "cold-weather reliability event" in NERC's sense: the cause (freezing or not) is
  unknown, so this measures repeat trips in cold events, not repeat freeze failures.
- State strata only partly remove geography. Two events can hit the same cold corner of a state.
- Units that retired, or did not run hard in both events, drop out of a pair. Units that ran in only one
  event say nothing about repeats.
- POST compares different storms than PRE. A milder storm lowers trip counts, but the risk ratio is a
  relative measure, and the state strata absorb part of the difference. It is still not a controlled
  experiment.
- Missing CEMS rows count as zero (outage-1's rule), so a reporting gap after hard running looks like a
  trip.

## Code and job

`outage/repeat_core.py` (standard library; hand-checked tests in `outage/test_repeat_core.py`) and
`outage/repeat_job.py`. The job waits until this file is public with the line "Pre-registration id:
repeat-1." Outputs: `repeat1.json`, `repeat1.md`, `repeat1_pairs.csv`, `repeat1_units.csv`.

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Code Apache-2.0; text and data CC BY 4.0.
