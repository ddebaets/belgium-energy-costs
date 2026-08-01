"""Belgium Energy Costs integration."""
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    CONF_GAS,
    CONF_ENABLED,
    CONF_ENGIE_ELEC_PEAK,
    CONF_ENGIE_ELEC_OFFPEAK,
    CONF_ENGIE_GAS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.DATE]

# Bump this when the config-entry schema or entity unique-ID format changes.
# HA will call async_migrate_entry for entries stored at a lower version.
CONFIG_ENTRY_VERSION = 2

# Reject YAML-only setup gracefully.
CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({}, extra=vol.ALLOW_EXTRA)},
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Reject YAML setup and guide users to the UI config flow."""
    if DOMAIN in config:
        _LOGGER.error(
            "Belgium Energy Costs: YAML configuration is no longer supported. "
            "Please set up the integration via Settings → Devices & Services → "
            "Add Integration → Belgium Energy Costs."
        )
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config-entry versions to the current schema.

    Version 1 → 2
    --------------
    Sensor unique IDs changed from ``belgium_energy_costs_{suffix}`` to
    ``belgium_energy_costs_{entry_id}_{suffix}`` so that multiple config
    entries never collide.  We rewrite the entity registry in-place so
    existing entity IDs (and therefore all dashboard cards) are preserved.
    """
    _LOGGER.info(
        "Migrating Belgium Energy Costs entry from version %s to %s",
        entry.version,
        CONFIG_ENTRY_VERSION,
    )

    if entry.version == 1:
        ent_reg = er.async_get(hass)
        entry_id = entry.entry_id

        # All suffixes used by v1 sensors (unique_id = f"{DOMAIN}_{suffix}")
        old_suffixes = [
            "months_since_contract_start",
            "total_electricity_cost_peak",
            "total_electricity_cost_off_peak",
            "total_electricity_cost",
            "total_electricity_injection_price",
            "electricity_peak_vs_off_peak_savings",
            "total_gas_cost",
            "electricity_peak_consumption_since_contract_start",
            "electricity_off_peak_consumption_since_contract_start",
            "electricity_consumption_since_contract_start",
            "electricity_total_export_since_contract_start",
            "electricity_injection_revenue_since_contract_start",
            "electricity_total_cost_since_contract_start",
            "electricity_net_cost_since_contract_start",
            "electricity_estimated_annual_cost",
            "electricity_estimated_annual_injection_revenue",
            "gas_total_cost_since_contract_start",
            "gas_estimated_annual_cost",
            "total_energy_cost_since_contract_start",
            "total_estimated_annual_energy_cost",
            "electricity_avg_monthly_consumption",
            "electricity_avg_monthly_cost",
            "gas_avg_monthly_consumption",
            "gas_avg_monthly_cost",
            "gas_consumption_kwh",
            "gas_consumption_m3",
            "total_avg_monthly_cost",
        ]

        migrated = 0
        for suffix in old_suffixes:
            old_uid = f"{DOMAIN}_{suffix}"
            new_uid = f"{DOMAIN}_{entry_id}_{suffix}"
            entity = ent_reg.async_get_entity_id("sensor", DOMAIN, old_uid)
            if entity:
                ent_reg.async_update_entity(entity, new_unique_id=new_uid)
                migrated += 1

        # Also migrate the gas number entity
        old_gas_uid = f"{DOMAIN}_gas_meter_reading"
        new_gas_uid = f"{DOMAIN}_{entry_id}_gas_meter_reading"
        gas_entity = ent_reg.async_get_entity_id("number", DOMAIN, old_gas_uid)
        if gas_entity:
            ent_reg.async_update_entity(gas_entity, new_unique_id=new_gas_uid)
            migrated += 1

        _LOGGER.info(
            "Belgium Energy Costs migration v1→v2: updated %d entity unique IDs",
            migrated,
        )

        hass.config_entries.async_update_entry(entry, version=CONFIG_ENTRY_VERSION)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Belgium Energy Costs from a config entry."""
    await _warn_missing_engie_sensors(hass, entry.data)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_register_services(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    _LOGGER.info("Belgium Energy Costs loaded (entry %s)", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # Also drop the per-entry year-history state (sensor refs + closures),
        # else it leaks across reloads since _close_year reloads the entry.
        hass.data.get(DOMAIN, {}).get("_year_history", {}).pop(entry.entry_id, None)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _warn_missing_engie_sensors(hass: HomeAssistant, config: dict) -> None:
    """Log warnings for missing ENGIE Belgium sensors (non-blocking)."""
    missing: list[str] = []
    for key in (CONF_ENGIE_ELEC_PEAK, CONF_ENGIE_ELEC_OFFPEAK):
        entity_id = config.get(key, "")
        if entity_id and not hass.states.get(entity_id):
            missing.append(entity_id)
    if config.get(CONF_GAS, {}).get(CONF_ENABLED, False):
        entity_id = config.get(CONF_ENGIE_GAS, "")
        if entity_id and not hass.states.get(entity_id):
            missing.append(entity_id)
    if missing:
        _LOGGER.warning(
            "Belgium Energy Costs: ENGIE Belgium sensors not found at startup: %s. "
            "Sensors will be unavailable until the hass-engie-be integration is ready.",
            ", ".join(missing),
        )


async def _async_register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register integration-level services (idempotent)."""
    if hass.services.has_service(DOMAIN, "update_gas_reading"):
        return

    async def _handle_update_gas_reading(call) -> None:
        from .const import get_gas_meter_entity_id
        reading: float = call.data["reading"]
        entity_id = get_gas_meter_entity_id(entry.entry_id)
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": entity_id, "value": reading},
            blocking=True,
        )
        _LOGGER.info("Gas meter reading updated to %.3f m³", reading)

    hass.services.async_register(
        DOMAIN, "update_gas_reading", _handle_update_gas_reading,
        schema=vol.Schema({vol.Required("reading"): vol.Coerce(float)}),
    )

    async def _close_year(entry_id: str, util: str, period_end_iso: str | None = None,
                          *, reload: bool = True) -> bool:
        """Close the current contract year for one utility of one config entry.

        Records the utility's current lifetime ("since contract start") values
        as a snapshot, from which per-year deltas are derived. ``period_end_iso``
        lets you record the *actual* billing end (e.g. the meter-read date),
        which can differ from the calendar anniversary. Returns True if a
        snapshot was written. Fail-safe: logs and returns False on any error.
        """
        from datetime import date as _date

        store = hass.data.get(DOMAIN, {}).get("_year_history", {}).get(entry_id)
        if not store:
            _LOGGER.warning(
                "close contract year: no year-history state for entry %s; "
                "is the integration fully loaded?", entry_id,
            )
            return False

        meta = store.get(util)
        if not meta:
            _LOGGER.warning("close contract year: utility '%s' not configured", util)
            return False

        history = store["history"]
        try:
            from .contract_year import _safe_anniversary

            start = meta["start"]
            metrics = meta["metrics"]          # cumulative consumption sensors
            cost_fn = meta["cost_fn"]          # freezes this year's cost

            # Abort if any consumption sensor isn't ready yet: coercing a missing
            # reading to 0.0 would store a wrong cumulative baseline and make the
            # NEXT period double-count. (Only realistically possible in the first
            # seconds after a restart.)
            if any(s.native_value is None for s in metrics.values()):
                _LOGGER.warning(
                    "Skipping contract-year close for '%s': a consumption sensor "
                    "is not ready (None). Try again once values are populated.", util,
                )
                return False

            # Lifetime cumulative consumption at close (for next-year deltas).
            cumulative = {k: float(s.native_value or 0.0) for k, s in metrics.items()}

            today = _date.today()
            # Resolve period_end, in priority order:
            #   1. explicit arg (cv.date object or ISO string)
            #   2. the utility's dashboard date-picker entity, if the user set one
            #   3. today
            if isinstance(period_end_iso, _date):
                period_end = period_end_iso
            elif period_end_iso:
                period_end = _date.fromisoformat(str(period_end_iso))
            else:
                period_end = today
                from .const import get_close_date_entity_id
                picker = hass.states.get(get_close_date_entity_id(entry_id, util))
                if picker and picker.state not in (None, "", "unknown", "unavailable"):
                    try:
                        period_end = _date.fromisoformat(picker.state)
                    except (ValueError, TypeError):
                        pass

            # Guard against a stale or future period_end. A left-over picker
            # value (typically the PREVIOUS close's date) resolves ≤ the last
            # period_end; meter reads are never in the future. Either case
            # falls back to today rather than corrupting period boundaries.
            lower_bound = history.last_period_end(util) or start
            if period_end <= lower_bound or period_end > today:
                _LOGGER.warning(
                    "close contract year: ignoring implausible period_end %s for "
                    "'%s' (must be after %s and not in the future); using today",
                    period_end, util, lower_bound,
                )
                period_end = today

            next_index = history.completed_year_count(util) + 1

            # This year's own consumption = lifetime − previous close cumulative.
            base = history.last_cumulative(util)
            year_cons = {k: max(0.0, cumulative.get(k, 0.0) - base.get(k, 0.0)) for k in cumulative}

            # Guard: a contract year with ZERO consumption is never a real close.
            # This blocks spurious closes (e.g. an automatic rollover firing right
            # after a manual one, or a reload re-trigger) from inserting an empty
            # phantom year. Manual closes of a genuinely-empty year are vanishingly
            # rare; if needed, the user can still close after some usage exists.
            if sum(year_cons.values()) <= 0.0:
                _LOGGER.warning(
                    "Skipping contract-year close for '%s': zero consumption "
                    "since last close (would create an empty phantom year).", util,
                )
                return False

            # Months in the year being closed: anniversary that started it → period_end.
            year_start = _safe_anniversary(start, start.year + (next_index - 1))
            months = max(0.0, (period_end - year_start).days / 30.44)
            # FREEZE the cost using the same formula the live sensor uses.
            year_cost = cost_fn(year_cons, months)

            await history.async_append_snapshot(
                util, next_index, start,
                period_end=period_end, closed_on=today,
                cumulative=cumulative, year_cost=year_cost,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("close contract year failed for utility '%s'", util)
            return False

        # The picker's value has been consumed by this close — clear it so it
        # can't silently become the next close's period_end. Before the reload,
        # so RestoreEntity restores the cleared state afterwards.
        try:
            picker_entity = hass.data.get(DOMAIN, {}).get(
                "_close_date_entities", {}
            ).get(entry_id, {}).get(util)
            if picker_entity:
                await picker_entity.async_clear()
        except Exception:  # noqa: BLE001 - clearing is best-effort
            _LOGGER.exception("failed to clear %s close-date picker", util)

        if reload:
            await hass.config_entries.async_reload(entry_id)
        return True

    def _all_entry_ids() -> list[str]:
        """All config-entry IDs that have year-history state stashed."""
        return list(hass.data.get(DOMAIN, {}).get("_year_history", {}).keys())

    async def _handle_close_elec(call) -> None:
        for eid in _all_entry_ids():
            await _close_year(eid, "elec", call.data.get("period_end"))

    async def _handle_close_gas(call) -> None:
        for eid in _all_entry_ids():
            await _close_year(eid, "gas", call.data.get("period_end"))

    _period_end_schema = vol.Schema({
        vol.Optional("period_end"): cv.date,
    })

    if not hass.services.has_service(DOMAIN, "close_electricity_billing_period"):
        hass.services.async_register(
            DOMAIN, "close_electricity_billing_period",
            _handle_close_elec, schema=_period_end_schema,
        )
    if not hass.services.has_service(DOMAIN, "close_gas_billing_period"):
        hass.services.async_register(
            DOMAIN, "close_gas_billing_period",
            _handle_close_gas, schema=_period_end_schema,
        )

    async def _undo_last_close(entry_id: str, util: str) -> None:
        """Remove the most recent contract-year snapshot for *util* (undo)."""
        store = hass.data.get(DOMAIN, {}).get("_year_history", {}).get(entry_id)
        if not store or not store.get(util):
            _LOGGER.warning("undo close: utility '%s' not available", util)
            return
        try:
            removed = await store["history"].async_remove_last_snapshot(util)
            if removed:
                await hass.config_entries.async_reload(entry_id)
            else:
                _LOGGER.info("undo close: no snapshot to remove for '%s'", util)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("undo close failed for utility '%s'", util)

    async def _handle_undo_elec(call) -> None:
        for eid in _all_entry_ids():
            await _undo_last_close(eid, "elec")

    async def _handle_undo_gas(call) -> None:
        for eid in _all_entry_ids():
            await _undo_last_close(eid, "gas")

    if not hass.services.has_service(DOMAIN, "undo_electricity_billing_period"):
        hass.services.async_register(
            DOMAIN, "undo_electricity_billing_period", _handle_undo_elec,
            schema=vol.Schema({}),
        )
    if not hass.services.has_service(DOMAIN, "undo_gas_billing_period"):
        hass.services.async_register(
            DOMAIN, "undo_gas_billing_period", _handle_undo_gas,
            schema=vol.Schema({}),
        )

    # --- Automatic anniversary rollover (daily check, per utility) ----------
    # Fires once per day; closes a utility's year only if its calendar
    # anniversary has passed AND it hasn't already been closed manually
    # (so an early manual close suppresses the auto one — no double-count).
    async def _daily_rollover_check(now=None) -> None:
        # This timer is registered per config entry, so it scopes to this entry.
        from datetime import date as _date
        from .contract_year import due_year_index

        store = hass.data.get(DOMAIN, {}).get("_year_history", {}).get(entry.entry_id)
        if not store:
            return
        history = store["history"]
        today = _date.today()
        did_close = False
        for util in ("elec", "gas"):
            meta = store.get(util)
            if not meta:
                continue
            try:
                already = history.completed_year_count(util)
                if due_year_index(meta["start"], today, already) is not None:
                    # reload once at the end, not per-utility
                    if await _close_year(entry.entry_id, util, reload=False):
                        did_close = True
            except Exception:  # noqa: BLE001
                _LOGGER.exception("auto rollover check failed for utility '%s'", util)
        if did_close:
            await hass.config_entries.async_reload(entry.entry_id)

    # Run shortly after midnight every day. We deliberately do NOT run the
    # check eagerly on setup: setup re-runs on every reload (and _close_year
    # reloads), so an eager call creates a reload cascade. The daily timer plus
    # the zero-consumption guard in _close_year are sufficient — a genuinely
    # missed anniversary is caught at the next midnight tick, and the guard
    # prevents any spurious empty close in the meantime.
    entry.async_on_unload(
        async_track_time_change(hass, _daily_rollover_check, hour=0, minute=5, second=0)
    )
