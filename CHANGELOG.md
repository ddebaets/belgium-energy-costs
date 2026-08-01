# Changelog

All notable changes to the Belgium Energy Costs integration are documented here.

## [5.11.1] - 2026-08-01

### Fixed
- **Stale period-end picker footgun.** The close services read the dashboard
  date picker as the period_end — but the picker kept its value after a close,
  so the *previous* close's date would silently be reused for the next one,
  corrupting period boundaries (and the year-end projection's anchoring).
  Two-layer fix: the close service now rejects implausible dates (on or before
  the last period end, or in the future) with a fallback to today, and the
  picker is automatically cleared after every successful close.

## [5.11.0] - 2026-08-01

Solar-aware year-end projection — honest estimates through a mid-contract solar installation.

### Added
- **Projected year-end cost sensors.** `sensor.electricity_projected_year_end_cost`,
  `sensor.gas_projected_year_end_cost`, and `sensor.total_projected_year_end_cost`
  project the **current billing year**: the actual (frozen) cost so far this period
  plus a month-by-month seasonal model of the remaining months. Unlike the
  "estimated annual" sensors (lifetime average × 12), these stay honest when the
  household changes regime — the motivating case being a solar + battery
  installation, where history over-predicts and the summer run-rate under-predicts
  winter. Electricity models remaining import as
  `load(m) − self-consumed PV(m)` using Belgian seasonal shapes (Synergrid
  residential load, PVGIS Brussels PV yield, Belgian gas heating profile — all in
  the new `projection.py`, normalised and calibratable). The total sensor is **net
  of projected solar injection revenue** (gross + per-utility breakdown in
  attributes; every monthly model row exposed for inspection).
- **Annual PV generation estimate** (kWh/year) in the solar setup step and options
  flow — anchors the PV term of the projection. `0` disables the PV term, cleanly
  degrading to a seasonal (non-solar) projection.
- **Solar / injection tracking in the options flow.** Households that install
  panels mid-contract can now enable export tracking (sensor, baseline at
  installation, PV estimate) without deleting and re-adding the integration.

## [5.10.0] - 2026-06-13

Wallonia grid-cost support (ORES defaults). _(Entry backfilled — released without
a changelog entry.)_

### Added
- Walloon region enabled with ORES default tariffs (largest DSO, ~75% of
  Wallonia), from the ENGIE Wallonia prices & conditions sheets. Other Walloon
  DSOs (RESA / AIEG / AIESH / Régie de Wavre) documented in `const.py` for manual
  adjustment. Setup and options cost steps pull region-aware defaults;
  Brussels values unchanged.

## [5.9.0] - 2026-06-04

Per-billing-period tracking, accurate cost accounting, and a ready-made dashboard.

### Added
- **Billing-period history.** Each contract year is recorded as a closed period
  with its own consumption (kWh, m³) and a **frozen cost** captured at close — so
  closed periods always match what you were billed and never drift when prices
  change later. New sensors:
  `sensor.electricity_billing_period_history`, `sensor.gas_billing_period_history`
  (state = number of closed periods; full per-period breakdown in attributes), and
  `sensor.electricity_cost_this_billing_period`, `sensor.gas_cost_this_billing_period`
  (cost so far in the current period).
- **Close a billing period — manually or automatically.** Services
  `close_electricity_billing_period` / `close_gas_billing_period` (with an optional
  `period_end` date for backdating / early meter reads), and matching
  `undo_*` services to reverse a close. Periods also roll over **automatically** on
  the contract anniversary (a daily check; a manual early close suppresses the
  automatic one so a period is never closed twice).
- **Period-end date pickers.** New `date` entities per utility let you set the exact
  billing-period end on the dashboard before closing.
- **Continuous cost accumulator.** New `sensor.electricity_cost_accumulated` /
  `sensor.gas_cost_accumulated` price each kWh at the rate in force **when it was
  consumed** (like the HA Energy dashboard), so they don't re-price history when the
  ENGIE price moves. Accurate from first run (they seed from the current meter
  reading; not retroactive).
- **Ready-made dashboard** at `dashboards/belgium_energy_costs_dashboard.yaml` —
  built-in cards only, with a year-over-year comparison table and close controls.
  Import instructions and the one required entity-ID edit are documented in the file.

### Notes
- Electricity and gas are tracked independently (they can have different contract
  anniversaries).
- All of the above is **additive and fail-safe**: if any new component fails to
  initialise it is logged and skipped, leaving the core cost sensors unaffected.
- Existing entity IDs are unchanged, so dashboards and history carry over.

## [5.8.0] - 2026-05-31

### Added
- **Editable gas conversion factor.** A new "📐 Update Gas Conversion Factor" option
  in the integration's options flow lets you change the kWh/m³ factor after setup —
  no reinstall needed. The most accurate value is your own: divide the kWh billed on
  your annual statement by the m³ consumed over the same period.

### Changed
- **SIBELGA (Brussels) default conversion factor: 11.2 → 11.39 kWh/m³.** Calibrated
  against a full 359-day SIBELGA gas bill (1481 m³ → 16 865 kWh). The old 11.2
  placeholder under-counted gas energy by ~1.65%. New installs use 11.39 automatically;
  existing installs keep their configured value — update it via the new options step
  above if you want the calibrated default.

## [5.7.1] - 2026-05-31

### Changed
- **Consistent display precision on all sensors.** The base sensor now declares a
  unit-driven `suggested_display_precision`: currency amounts (totals, monthly
  averages, annual projections, export revenue) show exactly two decimals in the
  dashboard, Energy tab, and history — no more values like `1495.0 €` — while
  per-kWh price sensors keep five decimals so rates stay meaningful. Existing
  installs pick this up automatically on update (a manual per-entity
  display-precision override, if you set one, still takes priority).

> Note: 5.7.0 bumped the version metadata but did not include the code change;
> 5.7.1 carries the actual fix. Update straight to 5.7.1.

## [5.6.0] - 2026-05-24

### Added
- **"Update ENGIE Sensors" option in the options flow** — re-select your ENGIE Belgium
  price sensors without reinstalling the integration. Use this after upgrading
  hass-engie-be to v0.9.0, which changes entity IDs from customer account number (CAN)
  to business agreement number (BAN) format and requires a full reinstall of that
  integration. Your contract dates, cost components, and baseline readings are preserved.

## [5.5.0] - 2026-04-15

### Added
- Dynamic ENGIE sensor selection in the setup wizard — compatible with hass-engie-be v0.8.2,
  which changed entity IDs to include the account ID and EAN number.

## [5.4.0] - 2026-04-03

This release is a near-complete architectural rewrite focused on correctness,
reliability, and user experience. Upgrading from any previous version is
supported via automatic entity registry migration (no manual steps needed).

### Breaking changes
- Config entry version bumped from 1 → 2. HA runs `async_migrate_entry`
  automatically on first load, rewriting entity unique IDs in the registry.
  All existing entity IDs (what your dashboard cards reference) are preserved.

### Architecture
- **Event-driven debouncer** (`_UpdateThrottle`): a shared per-entry object
  sits between raw HA state-change events and sensor state writes. Each source
  entity (P1 meter, ENGIE price, gas number entity) now has exactly **one** HA
  subscription regardless of how many sensors depend on it. Rapid P1 meter
  ticks are absorbed and flushed as a single batch after a 5-second quiet
  window, reducing event-loop pressure by ~9× in a typical bi-horaire + gas
  + solar setup.
- **Direct object references**: derived sensors (costs, averages, totals) hold
  Python references to their dependency sensors and call `.native_value`
  directly — no `hass.states.get("sensor.…")` round-trips on sibling sensors,
  eliminating a class of startup race conditions.
- **Entry-scoped unique IDs**: all sensor and number entity unique IDs now
  include the config entry ID (`{DOMAIN}_{entry_id}_{suffix}`) so multiple
  installations never collide in the entity registry.

### Config flow
- **8-step wizard** (down from 9): electricity and gas contract start dates
  are now collected together in step 2, with clear per-field labels
- **Separate contract start dates**: electricity and gas contracts can have
  different start dates; gas sensors use the gas contract date for their
  month-elapsed calculations independently of electricity sensors
- **Gas current meter reading is now required**: the setup wizard enforces
  entry of today's meter reading (validated ≥ baseline), preventing the
  large negative consumption values that occurred when the field was left at 0
- **ENGIE sensor check is non-blocking**: the check that previously hard-blocked
  setup if ENGIE sensors weren't visible (a timing issue, not an install issue)
  is now a warning-only log message
- **Step progress indicator**: every step title shows "Step X of 8 –" so users
  always know where they are in the wizard
- **All `NumberSelector` fields use `BOX` mode**: sliders are completely removed
  from the UI — all numeric inputs use text boxes

### Options flow
- Fixed `BelgiumEnergyCostsOptionsFlow.__init__` signature — HA 2024+ no longer
  passes `config_entry` to `OptionsFlow.__init__`; it is now accessed via
  `self.config_entry`
- Fixed options menu `step_id`: changed from `"menu"` to `"init"` so HA
  correctly resolves translations for menu item labels
- Menu labels now show: ⚡ Update Electricity Costs, 🔥 Update Gas Costs,
  🔢 Update Gas Meter Reading

### Sensors
- Removed `/year` and `/month` suffixes from all sensor units of measurement
  (`€`, `kWh`, `m³` only) — time period is conveyed by sensor name and card
  label instead
- Gas sensors now inherit from `_GasSensorBase` which overrides
  `_contract_start` with the gas-specific contract date
- All consumption sensors clamp to `max(0, current - baseline)` — prevents
  large negative readings on first boot before entity restoration completes
- `_calculate_months_since_start` now uses `time.min` (correct) instead of
  `datetime.min.time()` (worked but semantically wrong)

### Number entity (gas meter)
- `self.entity_id` is now set explicitly using `get_gas_meter_entity_id(entry_id)`
  with the entry ID **lowercased** (ULIDs contain uppercase; entity IDs must be
  lowercase) — fixes HA warning about invalid entity IDs
- Removed `_attr_has_entity_name = True` which caused HA to derive an
  unpredictable entity ID from device name + entity name; entity ID is now
  fully explicit and stable
- `async_write_ha_state()` is called immediately after restore so gas sensors
  never read `unknown` and compute a negative consumption

### Bug fixes
- Fixed shallow copy in options flow (`dict()` → `copy.deepcopy()`) that was
  silently mutating `ConfigEntry.data` nested dicts in-place
- Fixed duplicate `gas_baseline_m3` assignment in gas config processing
- Fixed `from datetime import datetime` inside `async_setup_entry` function body
  (moved to module-level import)
- Fixed legacy `async_setup` (YAML) using deprecated
  `hass.helpers.discovery.async_load_platform` — now logs a clear error
  directing users to the UI and returns cleanly

### Translations
- Added `translations/en.json` (HA frontend reads this; `strings.json` alone
  is not sufficient)
- All 8 config flow steps and all 4 options flow steps now have complete
  `title`, `description`, and `data` label definitions
- All field labels match their `vol.Schema` key names exactly

### Migration
- `async_migrate_entry` (v1 → v2) rewrites all 28 sensor and number entity
  unique IDs in the entity registry, preserving existing entity IDs and
  dashboard cards

---

## [5.3.0] - 2026-04-01

- Sensor chaining via HA state bus removed (direct object references)
- Unique IDs scoped to config entry
- Gas meter entity ID scoped to config entry
- Shallow copy bug fixed in options flow
- Gas current reading default-to-zero bug fixed
- Legacy YAML `async_setup` cleaned up
- `strings.json` completed for all steps
- `async_migrate_entry` added for v1 → v2

## [5.2.0] - 2026-03-29

- Total estimated annual energy cost sensor aggregation fixed
- Gas conversion factor field UI slider removed
- Duplicate sensor creation bug removed

## [5.1.0] - 2026-03-29

- Gas consumption sensors (m³ and kWh)
- Monthly average consumption and cost sensors
- Total average monthly energy cost sensor

## [5.0.0] - 2026-03-29

- Complete sensor architecture (40+ sensors)
- Enhanced gas tracking with consumption and cost breakdown
- Monthly and annual projections

## [4.3.0] - 2026-03-29

- Baseline number input fixed (division by 1000 bug)

## [4.0.0] - 2026-03-29

- Auto-created gas meter number entity
- Service for gas meter updates
- Options flow for cost updates without restart

## [3.0.0] - 2026-03-29

- Full UI config flow (8-step wizard)
- Regional support framework

## [2.0.0] - 2026-03-29

- Initial config flow implementation

## [1.0.0] - 2026-03-29

- Initial release — YAML configuration, Brussels support, P1 + solar + gas tracking
