"""Number platform for Belgium Energy Costs – Gas Meter Reading."""
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
    get_gas_meter_entity_id,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the gas meter number entity from a config entry."""
    if not entry.data.get(CONF_GAS, {}).get(CONF_ENABLED, False):
        return

    gas_config = entry.data[CONF_GAS]
    baseline = gas_config.get(CONF_BASELINE_READING_M3, 0.0)
    current_reading = gas_config.get("current_reading_m3", baseline)

    async_add_entities(
        [GasMeterReadingNumber(entry.entry_id, current_reading, baseline)],
        update_before_add=True,
    )
    _LOGGER.info(
        "Gas meter reading entity created (entry %s, initial value %.3f m³)",
        entry.entry_id,
        current_reading,
    )


class GasMeterReadingNumber(NumberEntity, RestoreEntity):
    """Editable number entity representing the physical gas meter in m³.

    The entity_id is set explicitly to match what get_gas_meter_entity_id()
    returns, so gas sensors can always find it regardless of how HA would
    otherwise derive the entity_id from the device/entity name.
    """

    # Do NOT use _attr_has_entity_name = True — that makes HA derive the
    # entity_id from device name + entity name, which we can't control.
    # Instead we set a fully explicit entity_id below.
    _attr_has_entity_name = False
    _attr_icon = "mdi:meter-gas"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 999_999.0
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_mode = NumberMode.BOX

    def __init__(self, entry_id: str, initial_value: float, baseline: float) -> None:
        """Initialise the gas meter reading entity."""
        self._entry_id = entry_id
        self._baseline = baseline
        self._attr_native_value = initial_value

        # Scoped unique_id prevents collisions between multiple entries.
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_gas_meter_reading"

        # Explicit friendly name shown in the UI.
        self._attr_name = "Gas Meter Reading"

        # Force the entity_id to exactly what get_gas_meter_entity_id() returns
        # so gas sensors can reliably look it up via hass.states.get().
        self.entity_id = get_gas_meter_entity_id(entry_id)

    @property
    def device_info(self) -> dict[str, Any]:
        """Group under the integration's virtual device."""
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Belgium Energy Costs",
            "manufacturer": "Belgium Energy Costs",
            "model": "Energy Cost Tracker",
        }

    async def async_added_to_hass(self) -> None:
        """Restore the last known meter reading after a restart."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in (None, "unknown", "unavailable"):
            _LOGGER.info(
                "No previous gas meter state for entry %s; using initial value %.3f m³",
                self._entry_id,
                self._attr_native_value,
            )
        else:
            try:
                self._attr_native_value = float(last_state.state)
                _LOGGER.debug(
                    "Restored gas meter reading for entry %s: %.3f m³",
                    self._entry_id,
                    self._attr_native_value,
                )
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Could not restore gas meter reading for entry %s "
                    "(state=%r); keeping initial value %.3f m³",
                    self._entry_id,
                    last_state.state,
                    self._attr_native_value,
                )

        # Write state immediately so gas sensors never read 'unknown'.
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Handle a value change from the UI or a service call."""
        self._attr_native_value = value
        self.async_write_ha_state()
        _LOGGER.info(
            "Gas meter reading updated to %.3f m³ (entry %s)",
            value,
            self._entry_id,
        )
