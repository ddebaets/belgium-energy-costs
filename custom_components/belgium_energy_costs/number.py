"""Number platform for Belgium Energy Costs - Gas Meter Reading."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    CONF_GAS,
    CONF_ENABLED,
    CONF_BASELINE_READING_M3,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up gas meter number entity from config entry."""
    # Only create if gas is enabled
    if not entry.data.get(CONF_GAS, {}).get(CONF_ENABLED, False):
        return
    
    # Use current reading if available, otherwise baseline
    gas_config = entry.data[CONF_GAS]
    baseline = gas_config.get(CONF_BASELINE_READING_M3, 0)
    current_reading = gas_config.get("current_reading_m3", baseline)
    
    async_add_entities([GasMeterReadingNumber(entry.entry_id, current_reading)], True)
    _LOGGER.info("Created gas meter reading number entity with initial value: %s m³", current_reading)


class GasMeterReadingNumber(NumberEntity, RestoreEntity):
    """Number entity for gas meter reading in m³."""

    _attr_has_entity_name = True
    _attr_name = "Gas Meter Reading"
    _attr_icon = "mdi:meter-gas"
    _attr_native_min_value = 0
    _attr_native_max_value = 999999
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_mode = NumberMode.BOX

    def __init__(self, entry_id: str, baseline: float) -> None:
        """Initialize the gas meter reading number."""
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_gas_meter_reading"
        self._attr_native_value = baseline
        self._baseline = baseline

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Belgium Energy Costs",
            "manufacturer": "Belgium Energy Costs",
            "model": "Energy Cost Tracker",
        }

    async def async_added_to_hass(self) -> None:
        """Restore last state when added to hass."""
        await super().async_added_to_hass()
        
        # Restore previous value if available
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                try:
                    self._attr_native_value = float(last_state.state)
                    _LOGGER.debug(
                        "Restored gas meter reading: %s m³", 
                        self._attr_native_value
                    )
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Could not restore gas meter reading, using baseline: %s m³",
                        self._baseline
                    )
                    self._attr_native_value = self._baseline
        else:
            _LOGGER.info(
                "No previous gas meter reading found, using baseline: %s m³",
                self._baseline
            )

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        self._attr_native_value = value
        self.async_write_ha_state()
        _LOGGER.info("Gas meter reading updated to: %s m³", value)
