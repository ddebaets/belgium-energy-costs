"""Belgium Energy Costs integration."""
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    CONF_ELECTRICITY,
    CONF_GAS,
    CONF_ENABLED,
    CONF_METER_TYPE,
    METER_TYPE_BI_HORAIRE,
    ENGIE_SENSOR_ELEC_PEAK,
    ENGIE_SENSOR_ELEC_OFFPEAK,
    ENGIE_SENSOR_GAS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER]

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
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _warn_missing_engie_sensors(hass: HomeAssistant, config: dict) -> None:
    """Log warnings for missing ENGIE Belgium sensors (non-blocking)."""
    missing: list[str] = []
    meter_type = config.get(CONF_ELECTRICITY, {}).get(CONF_METER_TYPE)
    if meter_type == METER_TYPE_BI_HORAIRE:
        for entity_id in (ENGIE_SENSOR_ELEC_PEAK, ENGIE_SENSOR_ELEC_OFFPEAK):
            if not hass.states.get(entity_id):
                missing.append(entity_id)
    else:
        if not hass.states.get(ENGIE_SENSOR_ELEC_PEAK):
            missing.append(ENGIE_SENSOR_ELEC_PEAK)
    if config.get(CONF_GAS, {}).get(CONF_ENABLED, False):
        if not hass.states.get(ENGIE_SENSOR_GAS):
            missing.append(ENGIE_SENSOR_GAS)
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
