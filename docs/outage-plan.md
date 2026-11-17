# outage-1: can public hourly data rebuild the power-plant failures of America's big cold snaps?

Pre-registration id: outage-1.

Written on 2026-11-17 by AI agents working in the name of MV2 of Munim, Inc. (mv2@munimtech.com), before
any hourly data for this study was read. The code that does the work is in `outage/` (Apache-2.0). This
plan is not edited after publication. Any later change goes in a dated note below the plan, and results
go in `docs/outage.md`.

## Why this matters

In every big U.S. cold snap, power plants fail at the moment they are needed most. Uri (February 2021)
caused rolling blackouts across Texas and the central U.S., and Elliott (December 2022) forced load shed in
the Southeast. FERC and NERC investigate each event using NERC's Generating Availability Data System
(GADS) and the outage reports owners file. Those records are confidential. The public sees totals (for
example, "90,500 MW of unplanned outages at the worst point of Elliott") and a few plants named in news
reports. Nobody outside the industry can see which units failed, how quickly they came back, or whether
the same units fail storm after storm. Researchers who model correlated cold-weather failures (Murphy,
Sowell and Apt, *Applied Energy* 2019 and later papers) need GADS access to do so.

EPA's Continuous Emissions Monitoring data (CEMS, via EPA CAMPD) is public. It reports gross electrical
load hour by hour for almost every fossil unit of 25 MW or more since 1995. A unit that is running hard
and then drops to zero within an hour, and stays off, looks like a trip. **This study asks whether those
hourly signatures, read for seven cold events from 2011 to 2026, track the official FERC/NERC outage
totals. If they do, they give the first public, unit-by-unit record of which fossil units failed in Uri,
Elliott, January 2025 and Winter 2026 (Fern and Gianna).**

Prior work checked on 2026-11-17: the FERC/NERC event reports (totals by region, fuel and cause; no unit
list), ISO post-event reports (totals), news lists of a few named plants (Industrial Info Resources named
six for Fern), Niskanen Center and Grid Strategies (regional energy shortfall by fuel), and the GADS-based
academic papers. We found no published unit-level reconstruction of cold-weather trips from CEMS and no
validation of such a proxy against the official event totals.

**The "wow" if it works:** "From public emissions data alone, X GW of fossil units can be seen tripping at
the peak of Winter Storm Elliott, unit by unit. Across seven cold events the public signal ranks the events
the way the confidential official totals do (Spearman rho = Y)." If it fails, that is also worth knowing:
public data could not stand in for GADS, and the gap shows how much of the failure record stays hidden.

## Data (public, no key)

Catalyst Cooperative's PUDL nightly build (CC BY 4.0), read on the day the job runs:
`core_epacems__hourly_emissions` (EPA CEMS hourly), `core_eia860__scd_plants` (balancing authority, BA),
`core_eia860__scd_generators` (energy source, capacity), `core_epa__assn_eia_epacamd_subplant_ids`
(EPA unit to EIA generator crosswalk) and `core_eia__entity_plants` (plant names, display only).

## Events and official totals (fixed now)

Official figure = peak coincident incremental unplanned outages (outages, derates and failures to start,
all fuels), as published. Sources: 2011-2022 from the FERC-NERC Winter Storm Elliott presentation of
21 Sep 2023 (series 29,700 / 19,500 / 15,800 / 61,300 / 90,500 MW); January 2025 from FERC-NERC "January
2025 Arctic Events: A System Performance Review" (Apr 2025; 71,022 MW on 22 Jan 2025); Winter 2026 from
FERC-NERC "Arctic Events: A System Performance Review, Winter 2026" (Sep 2026; 68,169 MW on 26 Jan 2026).

| id | event | window (UTC, end exclusive) | area used here | official MW |
|---|---|---|---|---|
| E2011 | 2011 Southwest cold weather | 2011-02-01 to 2011-02-06 | SW2011: ERCOT + all plants in AZ, NM | 29,700 |
| E2014 | 2014 Polar Vortex | 2014-01-05 to 2014-01-09 | EAST_TX: Eastern + ERCOT | 19,500 |
| E2018 | 2018 South Central | 2018-01-15 to 2018-01-18 | SC2018: SPP, TVA, Southern, PowerSouth + MISO plants in AR, LA, MS, TX | 15,800 |
| E2021 | Winter Storm Uri | 2021-02-08 to 2021-02-21 | URI: ERCOT + SPP + MISO plants in AR, LA, MS, TX | 61,300 |
| E2022 | Winter Storm Elliott | 2022-12-21 to 2022-12-27 | EAST: U.S. Eastern Interconnection | 90,500 |
| E2025 | January 2025 Arctic events | 2025-01-03 to 2025-01-25 | EAST_TX_NOSE: Eastern + ERCOT minus Southern (SOCO) and PowerSouth (AEC) | 71,022 |
| E2026 | Winter 2026 (Fern, Gianna) | 2026-01-22 to 2026-02-03 | EAST_TX_NOSE | 68,169 |

The areas are our approximations of each report's footprint. They are built from each plant's EIA-860 BA
(latest report year at or before the event year, else the earliest later one) and the CEMS state. An
empty BA falls back to the state: the western states are Western, TX is ERCOT, and the rest are Eastern.
The official footprints are not exact BA lists, so the main test is a rank test, and the robustness check
uses one area (Eastern + ERCOT) for every event.

## Definitions (fixed now)

- **Unit**: a CEMS emissions unit (EIA plant id + EPA unit id). Hourly gross load in MW. An hour with no
  row counts as 0 MW.
- **Read span** for a window [start, end): 30 days before start through 6 hours after end.
- **Capability (cap)**: the 95th percentile (nearest rank) of the unit's positive hourly loads from the
  read-span start to the window end, or the maximum if it has fewer than 20 positive hours. Units with
  cap < 25 MW are ignored.
- **Trip** starting at hour i (i inside the window): load >= 0.6 cap in hours i-3 and i-2 (hour i-1 is the
  transition hour, any value), and load <= 0.02 cap in each of hours i to i+5. The trip lasts until the
  first later hour with load >= 0.3 cap. While tripped, the unit contributes cap minus its load (floored
  at 0) to each window hour. Only trips that start inside the window count, mirroring "incremental".
  A slow ramp to zero over two or more hours is not a trip.
- **T** (event trip peak) = the maximum over window hours of the summed contributions of units in the
  area. This is the CEMS counterpart of the official coincident peak.
- **Controls**: the same window shifted by -364, +364, -728, -1092, +728 days, in that order. The first
  two that overlap no event window and end inside CEMS coverage are used (for example E2026 uses
  2024-01-25 to 2024-02-06 and 2023-01-26 to 2023-02-07). Area membership uses the event year.
- **Fuel** of a unit: the class (COAL: BIT SUB LIG RC WC ANT SGC; GAS: NG; OIL: DFO RFO JF KER WO; else
  OTHER) holding the most capacity among its crosswalk generators' latest EIA-860 rows. A tie is OTHER, and
  a unit with no mapping is UNKNOWN.
- **Fuel trip rate** in an event: the summed cap of area units of that fuel with at least one trip,
  divided by the summed cap of area units of that fuel that ran at >= 0.6 cap in two consecutive hours from
  3 hours before the window to its end.
- **ERCOT T**: T computed over ERCOT plants only.

## Predictions (with our probabilities, fixed now)

- **P1 (main validation)**: over the events inside CEMS coverage (at least 5 needed), Spearman rho between
  T and the official MW is >= 0.70. *p = 0.50.*
- **P2 (signal above routine)**: T exceeds the larger of its two controls' T in all events, or all but one
  (at least 5 events with controls needed). *p = 0.70.*
- **P3 (scale)**: the median of T / official MW lies between 0.10 and 0.60. We expect CEMS to see only
  part of the total: it misses derates, failures to start, slow-ramp outages, and all wind, solar, nuclear
  and hydro. *p = 0.50.*
- **P4 (Texas)**: ERCOT T in Winter 2026 exceeds ERCOT T in January 2025 (officially 19,472 MW vs
  13,990 MW for the Texas Interconnection). *p = 0.55.*
- **P5 (fuel)**: in both Elliott and Winter 2026, the gas fuel trip rate exceeds the coal fuel trip rate.
  *p = 0.50.*

The probabilities are honest guesses made before any data was read. Each prediction is scored "held",
"failed" or "not scorable" by `outage_core.score`. Failures are reported as plainly as successes.

## Reported but not predicted

- Variants: off-hours 4 and 12 instead of 6; the single Eastern + ERCOT area for every event (Spearman for
  each).
- Peak hour of T per event, number of trips, trips by fuel, and the full trip list per event (plant, unit,
  state, BA, fuel, cap, trip start, return to service).
- Any trip at a plant under a DOE Federal Power Act 202(c) order during Winter 2026 will be pointed out in
  the write-up, as a description only.

## Known limits

- CEMS sees only fossil units of 25 MW or more. Derates, failures to start and slow-ramp outages are
  invisible to this trip rule, so T is a partial count by design. That is why the main test is a rank
  test and why P3 is a range.
- Gross load of combined-cycle plants is reported per combustion turbine. Some plants report the steam
  turbine's share with the CTs and some do not, so combined-cycle capability is uneven.
- A unit can be shut down on purpose, quickly, in an event (for example, to save fuel). The rule cannot
  tell that apart from a failure, so every named trip in the results is "consistent with a trip", not a
  confirmed forced outage. The controls measure how often the rule fires in ordinary weeks.
- Missing CEMS rows count as zero, so a reporting gap after hard running would look like a trip.
- Area footprints are approximate, and official totals mix fuels the proxy cannot see.
- Seven events are a small sample. A rank correlation over seven points is a coarse test.

## Code and job

`outage/outage_core.py` (standard library, hand-checked tests in `outage/test_outage_core.py`) and
`outage/outage_job.py` (reads PUDL over HTTP; it does not read hourly data until this file is public with
the line "Pre-registration id: outage-1."). Outputs: `outage1.json`, `outage1.md`, `outage1_trips.csv`.

MV2 of Munim, Inc. Made with AI agents working in MV2's name. Code Apache-2.0; text and data CC BY 4.0.
