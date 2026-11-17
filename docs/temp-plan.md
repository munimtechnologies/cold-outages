# temp-1: how much more often do U.S. coal and gas units trip in the cold? (pre-registration)

Pre-registration id: temp-1.

MV2 of Munim, Inc. (mv2@munimtech.com), 2026-11-17. Made with AI agents working in MV2's name.
Code Apache-2.0; text CC BY 4.0. This plan is written before any hourly data has been read for it, and
it will not be edited. Results go to `docs/temp.md`. Stage 1 of this project is `docs/outage-plan.md`
(outage-1).

## Question

Power plants fail more often in extreme cold. How much more is known from NERC's Generating
Availability Data System (GADS), which is confidential. Murphy, Sowell and Apt (Applied Energy 253,
113513, 2019) used PJM's GADS records for 1995-2018. They found forced-outage probabilities rise
steeply at cold (and hot) temperatures. NREL's ReEDS model uses their curves. Mahmud and Dubey
(arXiv 2610.04368, 2026) fit a Bayesian model to anonymised GADS gas events in New York. ESIG reports
a knee near -7 to -10 C, below which gas forced-outage rates went from about 10% to over 30% in Uri.
All of this rests on data the public cannot see or check, unit by unit.

temp-1 asks whether EPA's public hourly emissions data (CEMS) can measure the same temperature
dependence from the outside. For every coal and gas unit and every hour from 2016 to 2025, the method
is: was the unit running hard, did it drop to (almost) zero within an hour and stay off, and what was
the air temperature at the nearest weather station?

Prior-art check (2026-11-17): searches for CEMS-based inference of forced outages or of
temperature-dependent failure rates found none. Every source found used GADS, ISO outage data or one
owner's private data.

**The wow, if it works:** the first public, unit-level, reproducible measurement of how much more
often U.S. fossil plants trip in the cold. Anyone could rerun it after each winter and see which
technologies, and which units, carry the risk.

## Data (all public)

- EPA CEMS hourly gross load (`core_epacems__hourly_emissions`), EIA-860 generators
  (`core_eia860__scd_generators`: energy source, prime mover, capacity), plants
  (`core_eia__entity_plants`: name, latitude, longitude) and the EPA-EIA crosswalk
  (`core_epa__assn_eia_epacamd_subplant_ids`). All come from Catalyst Cooperative's PUDL nightly build
  (CC BY 4.0).
- NOAA ISD-Lite hourly air temperature (AWS Open Data mirror `noaa-isd-pds`, `isd-lite/data/<year>/`)
  and the station list `isd-history.csv`. The mirror was last updated 2025-08-30, so 2025 is covered
  only through about August. Hours without a temperature are left out.

## Definitions (fixed; implemented in `outage/temp_core.py`)

- **Years:** 2016-2025, in UTC hours. Each calendar year is handled on its own. The first 3 hours and
  the last few hours of each year cannot be at risk.
- **Unit:** an EPA CEMS unit (plant id, EPA unit id). Capability `cap` = the 95th percentile (nearest
  rank) of the unit's positive hourly gross loads in that calendar year when there are at least 20,
  else the largest. Units below 25 MW are skipped.
- **Class:** from the EIA-860 generators linked to the unit in the crosswalk, using each generator's
  latest record. The fuel class (COAL, GAS, OIL, OTHER) goes by summed capacity, and a tie gives
  OTHER. GAS is split by the prime mover with the most capacity: CA/CT/CS/CC = GAS_CC (combined cycle),
  GT = GAS_CT (simple-cycle turbine), ST = GAS_ST (steam), anything else = GAS_OTHER. "Gas" in the
  predictions means all four gas classes pooled.
- **At-risk hour i (primary rule "abrupt"):** the unit ran at >= 60% of `cap` in hours i-3 and i-2,
  and was above 30% of `cap` in hour i-1.
- **Trip at hour i:** an at-risk hour i in which the unit is at <= 2% of `cap` in each of hours i to
  i+5 (6 hours). A trip at i makes hour i+1 not at risk, so no trip is counted twice.
- **Variants (secondary, reported, not scored):** "stage1" (hour i-1 only needs to be above 2% of
  `cap`, close to outage-1's rule) and "long" (as abrupt, but off for 12 hours).
- **Temperature of an at-risk hour i:** the air temperature in hour i-1 at the plant's station. The
  station is the first of the 3 nearest U.S. ISD stations within 50 km (active from 2016 to at least
  2024) whose file for that year has at least 2,000 hourly temperatures. Gaps of up to 2 hours are
  filled from the nearest observation (the earlier one on a tie).
- **Bins:** below -20, then 5 C bins from -20 to 35, then 35 and above (13 bins).
  **Cold** = below -10 C. **Very cold** = below -15 C. **Near freezing** = -5 to 0 C.
  **Reference** = 10 to 20 C. **Hot** = 35 C and above.
- **Hazard** = trips / at-risk unit-hours. **Ratio** = hazard in a temperature set / hazard in the
  reference set.
- **Scorable:** a ratio counts only if the numerator set has >= 30 trips and >= 10,000 at-risk
  unit-hours and the reference set has >= 30 trips. Otherwise the prediction is "not scorable".
- **Uncertainty:** 95% interval from 2,000 bootstrap resamples of whole weeks (all units together, so
  that a cold snap stays in one piece; seed 20261117). Intervals are reported. The predictions are
  scored on the point estimates.
- **Named storms (H4):** at-risk hours inside the seven outage-1 event windows (2011, 2014, 2018,
  2021, 2022, 2025, 2026; only 2018, 2021, 2022 and 2025 fall in 2016-2025) are dropped.
- **Placebo temperature (H5):** the same plant's station temperature 364 days earlier (same weekday,
  almost the same date), binned the same way. This keeps the season and the day of the week but breaks
  the link to the actual weather of that hour.

## Predictions (with MV2's probabilities, written before any data)

- **H1** Gas cold ratio >= 3. (p = 0.50)
- **H2** Coal cold ratio >= 1.5. (p = 0.50)
- **H3** Gas cold ratio > coal cold ratio. (p = 0.65)
- **H4** Gas cold ratio with the named-storm hours removed >= 2: the cold weakness is not only the
  big storms. (p = 0.50)
- **H5** Gas cold ratio with the true temperature / gas cold ratio with the placebo temperature
  >= 1.5: it is the weather, not just the season. (p = 0.55)
- **H6** Gas hot ratio (35 C and above vs reference) > 1. (p = 0.50)
- **H7** A knee, not a line: the gas near-freezing ratio is < 1.5 and the gas very-cold ratio is
  >= 3. (p = 0.35)

Each prediction will be reported as held, failed or not scorable. Nothing else is scored. Curves by
class, the variants, technology splits and a unit table (cold-hour trips per unit, labelled only
"consistent with a trip") will be reported as description.

## Known limits

- CEMS sees only units with emissions monitors. It does not see derates, failures to start, slow
  ramps down, nuclear, wind or solar. A "trip" here is a pattern in hourly data. A unit shut down on
  purpose within one hour looks the same. So each flagged event is only "consistent with a trip".
- The reference band (10-20 C) is the spring and autumn shoulder season, when planned maintenance and
  economic cycling are common. Both add non-failure "trips" to the reference hazard. That pushes cold
  ratios toward 1, so the cold ratios are likely to be underestimates.
- Peaking turbines (GAS_CT) start and stop for economic reasons all the time. Their hazard is mostly
  dispatch, so the GAS_CT curve is reported but not scored on its own.
- Hourly gross load is an hourly value. A trip late in hour i-1 can leave that hour high, while a fast
  planned shutdown can look like a trip.
- One station per plant, up to 50 km away, is a rough measure of the temperature at the plant.
  Stations change, and 2025 ends in about August.
- These are hazards per at-risk hour, not GADS forced-outage rates. The comparison with Murphy et al.
  and ESIG is about shape (how much more, and where the knee is), not level.

## Status at pre-registration

Core definitions and hand-checked tests: `outage/temp_core.py`, `outage/test_temp_core.py`. The data
job that applies them to CEMS and ISD-Lite is not yet written. When it is, it will use these
definitions unchanged, and any change to the code will be listed in `docs/temp.md`.
