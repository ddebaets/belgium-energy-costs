"""Belgium Energy Costs integration."""
import logging
from datetime import datetime
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    CONF_CONTRACT_START_DATE,
    CONF_ELECTRICITY,
    CONF_GAS,
    CONF_METER_TYPE,
    CONF_IMPORT,
    CONF_EXPORT,
    CONF_ENABLED,
    CONF_P1_SENSORS,
    CONF_BASELINE_READINGS,
    CONF_COSTS,
    CONF_CONVERSION_FACTOR,
    CONF_BASELINE_READING_M3,
    METER_TYPE_SINGLE,
    METER_TYPE_BI_HORAIRE,
    SENSOR_TOTAL,
    SENSOR_PEAK,
    SENSOR_OFFPEAK,
    DEFAULT_GAS_CONVERSION,
    COST_GREEN_CERT,
    COST_DIST_PEAK,
    COST_DIST_OFFPEAK,
    COST_DIST_SINGLE,
    COST_TRANSMISSION,
    COST_COTISATION,
    COST_ACCISE,
    COST_FIXED_MONTHLY,
    COST_GAS_DISTRIBUTION,
    COST_GAS_TRANSMISSION,
    COST_GAS_COTISATION,
    COST_GAS_ACCISE,
    COST_GAS_FIXED_MONTHLY,
    ENGIE_SENSOR_ELEC_PEAK,
    ENGIE_SENSOR_ELEC_OFFPEAK,
    ENGIE_SENSOR_GAS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER]

# Validation schemas
ELECTRICITY_COSTS_BI_HORAIRE_SCHEMA = vol.Schema({
    vol.Required(COST_GREEN_CERT): cv.positive_float,
    vol.Required(COST_DIST_PEAK): cv.positive_float,
    vol.Required(COST_DIST_OFFPEAK): cv.positive_float,
    vol.Required(COST_TRANSMISSION): cv.positive_float,
    vol.Required(COST_COTISATION): cv.positive_float,
    vol.Required(COST_ACCISE): cv.positive_float,
    vol.Required(COST_FIXED_MONTHLY): cv.positive_float,
})

ELECTRICITY_COSTS_SINGLE_SCHEMA = vol.Schema({
    vol.Required(COST_GREEN_CERT): cv.positive_float,
    vol.Required(COST_DIST_SINGLE): cv.positive_float,
    vol.Required(COST_TRANSMISSION): cv.positive_float,
    vol.Required(COST_COTISATION): cv.positive_float,
    vol.Required(COST_ACCISE): cv.positive_float,
    vol.Required(COST_FIXED_MONTHLY): cv.positive_float,
})

GAS_COSTS_SCHEMA = vol.Schema({
    vol.Required(COST_GAS_DISTRIBUTION): cv.positive_float,
    vol.Required(COST_GAS_TRANSMISSION): cv.positive_float,
    vol.Required(COST_GAS_COTISATION): cv.positive_float,
    vol.Required(COST_GAS_ACCISE): cv.positive_float,
    vol.Required(COST_GAS_FIXED_MONTHLY): cv.positive_float,
})

P1_SENSORS_SINGLE_SCHEMA = vol.Schema({
    vol.Required(SENSOR_TOTAL): cv.entity_id,
})

P1_SENSORS_BI_HORAIRE_SCHEMA = vol.Schema({
    vol.Required(SENSOR_PEAK): cv.entity_id,
    vol.Required(SENSOR_OFFPEAK): cv.entity_id,
})

BASELINE_READINGS_SINGLE_SCHEMA = vol.Schema({
    vol.Required(SENSOR_TOTAL): cv.positive_float,
})

BASELINE_READINGS_BI_HORAIRE_SCHEMA = vol.Schema({
    vol.Required(SENSOR_PEAK): cv.positive_float,
    vol.Required(SENSOR_OFFPEAK): cv.positive_float,
})

IMPORT_EXPORT_SCHEMA = vol.Schema({
    vol.Required(CONF_P1_SENSORS): vol.Any(
        P1_SENSORS_SINGLE_SCHEMA,
        P1_SENSORS_BI_HORAIRE_SCHEMA,
    ),
    vol.Required(CONF_BASELINE_READINGS): vol.Any(
        BASELINE_READINGS_SINGLE_SCHEMA,
        BASELINE_READINGS_BI_HORAIRE_SCHEMA,
    ),
})

EXPORT_SCHEMA = vol.Schema({
    vol.Required(CONF_ENABLED, default=False): cv.boolean,
    vol.Optional(CONF_P1_SENSORS): vol.Any(
        P1_SENSORS_SINGLE_SCHEMA,
        P1_SENSORS_BI_HORAIRE_SCHEMA,
    ),
    vol.Optional(CONF_BASELINE_READINGS): vol.Any(
        BASELINE_READINGS_SINGLE_SCHEMA,
        BASELINE_READINGS_BI_HORAIRE_SCHEMA,
    ),
})

ELECTRICITY_SCHEMA = vol.Schema({
    vol.Required(CONF_METER_TYPE): vol.In([METER_TYPE_SINGLE, METER_TYPE_BI_HORAIRE]),
    vol.Required(CONF_IMPORT): IMPORT_EXPORT_SCHEMA,
    vol.Optional(CONF_EXPORT, default={CONF_ENABLED: False}): EXPORT_SCHEMA,
    vol.Required(CONF_COSTS): vol.Any(
        ELECTRICITY_COSTS_SINGLE_SCHEMA,
        ELECTRICITY_COSTS_BI_HORAIRE_SCHEMA,
    ),
})

GAS_SCHEMA = vol.Schema({
    vol.Required(CONF_ENABLED, default=False): cv.boolean,
    vol.Optional(CONF_BASELINE_READING_M3): cv.positive_float,
    vol.Optional(CONF_CONVERSION_FACTOR, default=DEFAULT_GAS_CONVERSION): cv.positive_float,
    vol.Optional(CONF_COSTS): GAS_COSTS_SCHEMA,
})

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema({
            vol.Required(CONF_CONTRACT_START_DATE): cv.date,
            vol.Required(CONF_ELECTRICITY): ELECTRICITY_SCHEMA,
            vol.Optional(CONF_GAS, default={CONF_ENABLED: False}): GAS_SCHEMA,
        })
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Belgium Energy Costs integration."""
    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]
    
    # Validate ENGIE integration is available
    await _validate_engie_integration(hass, conf)
    
    # Store config in hass.data
    hass.data[DOMAIN] = conf
    
    # Forward setup to sensor platform
    await hass.helpers.discovery.async_load_platform(
        Platform.SENSOR, DOMAIN, conf, config
    )
    
    _LOGGER.info("Belgium Energy Costs integration initialized")
    return True


async def _validate_engie_integration(hass: HomeAssistant, config: dict) -> None:
    """Validate that required ENGIE Belgium sensors exist."""
    missing_sensors = []
    
    # Check electricity sensors based on meter type
    meter_type = config[CONF_ELECTRICITY][CONF_METER_TYPE]
    
    if meter_type == METER_TYPE_BI_HORAIRE:
        if not hass.states.get(ENGIE_SENSOR_ELEC_PEAK):
            missing_sensors.append(ENGIE_SENSOR_ELEC_PEAK)
        if not hass.states.get(ENGIE_SENSOR_ELEC_OFFPEAK):
            missing_sensors.append(ENGIE_SENSOR_ELEC_OFFPEAK)
    else:
        # For single tariff, we still need at least one price sensor
        if not hass.states.get(ENGIE_SENSOR_ELEC_PEAK):
            missing_sensors.append(ENGIE_SENSOR_ELEC_PEAK)
    
    # Check gas sensor if gas is enabled
    if config.get(CONF_GAS, {}).get(CONF_ENABLED, False):
        if not hass.states.get(ENGIE_SENSOR_GAS):
            missing_sensors.append(ENGIE_SENSOR_GAS)
    
    if missing_sensors:
        _LOGGER.warning(
            "Belgium Energy Costs: ENGIE Belgium integration sensors not found: %s. "
            "Please ensure hass-engie-be integration is installed and configured. "
            "Some cost calculations may not work correctly.",
            ", ".join(missing_sensors)
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Belgium Energy Costs from a config entry."""
    conf = entry.data
    
    # Validate ENGIE integration is available
    await _validate_engie_integration(hass, conf)
    
    # Store config in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = conf
    
    # Forward setup to platforms (sensor and number)
    # Number platform will auto-create gas meter entity if gas is enabled
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register services
    await _async_register_services(hass)
    
    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    _LOGGER.info("Belgium Energy Costs integration initialized via config entry")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)




async def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services."""
    
    async def async_update_gas_reading(call):
        """Handle update gas reading service call."""
        reading = call.data.get("reading")
        entity_id = f"number.{DOMAIN}_gas_meter_reading"
        
        await hass.services.async_call(
            "number",
            "set_value",
            {
                "entity_id": entity_id,
                "value": reading,
            },
            blocking=True,
        )
        
        _LOGGER.info("Updated gas meter reading to %s m³", reading)
    
    # Register service if not already registered
    if not hass.services.has_service(DOMAIN, "update_gas_reading"):
        hass.services.async_register(
            DOMAIN,
            "update_gas_reading",
            async_update_gas_reading,
            schema=vol.Schema({
                vol.Required("reading"): vol.Coerce(float),
            }),
        )

