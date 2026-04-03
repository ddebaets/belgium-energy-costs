# Changelog

All notable changes to the Belgium Energy Costs integration are documented here.

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
