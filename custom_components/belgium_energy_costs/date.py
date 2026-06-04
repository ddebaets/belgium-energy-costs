"""Date platform for Belgium Energy Costs — contract-year close dates.

Provides one editable date entity per utility ("elec", "gas"). The dashboard
exposes these as date pickers, and the close service reads them so a user can
pick the exact billing-period end (e.g. the meter-read date) before closing a
year — including backdating, which the dashboard buttons alone can't do.

Additive & fail-safe: if the gas connection isn't configured, the gas date
entity simply isn't created. Nothing here affects the core cost sensors.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    CONF_GAS,
    CONF_ENABLED,
    get_close_date_entity_id,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the contract-year close-date entities."""
    entities: list[ContractYearCloseDate] = [
        ContractYearCloseDate(entry.entry_id, "elec", "Electricity Billing Period End Date"),
    ]
    if entry.data.get(CONF_GAS, {}).get(CONF_ENABLED, False):
        entities.append(
            ContractYearCloseDate(entry.entry_id, "gas", "Gas Billing Period End Date")
        )
    async_add_entities(entities, update_before_add=True)


class ContractYearCloseDate(DateEntity, RestoreEntity):
    """Editable date used as the period_end when closing a contract year."""

    _attr_has_entity_name = False
    _attr_icon = "mdi:calendar-edit"

    def __init__(self, entry_id: str, utility: str, name: str) -> None:
        self._entry_id = entry_id
        self._utility = utility
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{utility}_close_date"
        self._attr_name = name
        self.entity_id = get_close_date_entity_id(entry_id, utility)
        self._attr_native_value: date | None = None

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Belgium Energy Costs",
            "manufacturer": "Belgium Energy Costs",
            "model": "Energy Cost Tracker",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state not in (None, "unknown", "unavailable"):
            try:
                self._attr_native_value = date.fromisoformat(last.state)
            except (ValueError, TypeError):
                self._attr_native_value = None
        self.async_write_ha_state()

    async def async_set_value(self, value: date) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
        _LOGGER.debug(
            "Contract-year close date for '%s' set to %s (entry %s)",
            self._utility, value.isoformat(), self._entry_id,
        )
