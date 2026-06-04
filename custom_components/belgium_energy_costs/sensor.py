"""Sensor platform for Belgium Energy Costs.

Architecture notes
------------------
* All sensors are **event-driven** (``_attr_should_poll = False``).  A
  ``DataUpdateCoordinator`` is intentionally *not* used here: coordinators are
  designed for polled/cloud data sources.  Our sources (ENGIE prices, P1 meters,
  gas number entity) push state-change events — reacting to those directly is both
  lower-latency and lower-overhead than polling.

* **Debouncing / fanout reduction**: a single P1 meter tick would otherwise wake
  up ~9 sensors simultaneously (consumption, total cost, annual, monthly average,
  combined total, …).  We use a per-source ``_UpdateThrottle`` that:
    1. Absorbs the first event immediately (zero extra latency on the first write).
    2. Schedules a single deferred flush after ``DEBOUNCE_SECONDS`` for any
       subsequent events that arrive within that window.
  All sensors that registered interest in the same source entity are flushed
  together in one pass, so HA receives a single batch of state writes instead of
  a cascade.

* **Direct object references**: derived sensors (costs, averages, totals) hold
  Python references to their dependency sensors and call ``.native_value``
  directly — no ``hass.states.get("sensor.…")`` round-trips on sibling sensors.

* **Entry-scoped unique IDs**: every unique_id includes the config-entry ID so
  multiple installations never collide.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time
from typing import Any, Callable

from homeassistant import config_entries
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CURRENCY_EURO,
    UnitOfEnergy,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .contract_year import (
    ContractYearHistory,
    UTILITY_ELEC,
    UTILITY_GAS,
    contract_year_label,
)
from homeassistant.util import dt as dt_util

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
    METER_TYPE_BI_HORAIRE,
    SENSOR_TOTAL,
    SENSOR_PEAK,
    SENSOR_OFFPEAK,
    DEFAULT_DAYS_PER_MONTH,
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
    CONF_ENGIE_ELEC_PEAK,
    CONF_ENGIE_ELEC_OFFPEAK,
    CONF_ENGIE_ELEC_INJECTION,
    CONF_ENGIE_GAS,
    SENSOR_MONTHS_SINCE_START,
    SENSOR_TOTAL_ELEC_PEAK,
    SENSOR_TOTAL_ELEC_OFFPEAK,
    SENSOR_TOTAL_ELEC_SINGLE,
    SENSOR_TOTAL_ELEC_INJECTION,
    SENSOR_ELEC_PEAK_OFFPEAK_SAVINGS,
    SENSOR_TOTAL_GAS,
    SENSOR_ELEC_PEAK_CONSUMPTION,
    SENSOR_ELEC_OFFPEAK_CONSUMPTION,
    SENSOR_ELEC_SINGLE_CONSUMPTION,
    SENSOR_ELEC_EXPORT_TOTAL,
    SENSOR_ELEC_EXPORT_REVENUE,
    SENSOR_ELEC_TOTAL_COST,
    SENSOR_ELEC_NET_COST,
    SENSOR_ELEC_ANNUAL_COST,
    SENSOR_ELEC_ANNUAL_REVENUE,
    SENSOR_GAS_TOTAL_COST,
    SENSOR_GAS_ANNUAL_COST,
    SENSOR_TOTAL_ENERGY_COST,
    SENSOR_TOTAL_ANNUAL_COST,
    get_gas_meter_entity_id,
)

_LOGGER = logging.getLogger(__name__)

# How long (seconds) to wait before flushing a batch of updates triggered by
# the same source entity.  P1 meters typically push every 1-10 s; 5 s is a
# good balance between responsiveness and write reduction.
DEBOUNCE_SECONDS: float = 5.0


# ---------------------------------------------------------------------------
# Shared debounce / batch-update throttle
# ---------------------------------------------------------------------------

class _UpdateThrottle:
    """Per-source-entity debouncer that batches sensor state writes.

    All ``BelgiumEnergyCostSensor`` instances that care about the same source
    entity register themselves here.  When that entity changes:

    * The first event in any window triggers an *immediate* flush (zero
      extra latency for the first real-time update).
    * Subsequent events within ``DEBOUNCE_SECONDS`` are absorbed; a single
      deferred flush is scheduled for after the quiet period ends.

    This collapses what would otherwise be N simultaneous
    ``async_write_ha_state`` calls (one per interested sensor) down to a single
    batch, reducing event-loop pressure proportionally.
    """

    def __init__(self, hass: HomeAssistant, debounce: float = DEBOUNCE_SECONDS) -> None:
        self._hass = hass
        self._debounce = debounce
        # source_entity_id → set of sensors
        self._listeners: dict[str, set[BelgiumEnergyCostSensor]] = {}
        # source_entity_id → pending asyncio.TimerHandle
        self._pending: dict[str, asyncio.TimerHandle] = {}
        # source_entity_id → HA unsubscribe callable
        self._unsubs: dict[str, Callable] = {}

    def register(
        self, sensor: "BelgiumEnergyCostSensor", source_entities: list[str]
    ) -> None:
        """Register *sensor* as a listener for each of *source_entities*."""
        for entity_id in source_entities:
            if entity_id not in self._listeners:
                self._listeners[entity_id] = set()
                self._unsubs[entity_id] = async_track_state_change_event(
                    self._hass, [entity_id], self._make_handler(entity_id)
                )
            self._listeners[entity_id].add(sensor)

    def unregister(self, sensor: "BelgiumEnergyCostSensor") -> None:
        """Remove *sensor* from all source subscriptions it was registered for."""
        empty_keys: list[str] = []
        for entity_id, listeners in self._listeners.items():
            listeners.discard(sensor)
            if not listeners:
                empty_keys.append(entity_id)

        for entity_id in empty_keys:
            self._listeners.pop(entity_id, None)
            if entity_id in self._pending:
                self._pending.pop(entity_id).cancel()
            if unsub := self._unsubs.pop(entity_id, None):
                unsub()

    def _make_handler(self, entity_id: str) -> Callable:
        @callback
        def _handler(event) -> None:
            self._on_source_change(entity_id)
        return _handler

    @callback
    def _on_source_change(self, entity_id: str) -> None:
        """Handle a state-change event for *entity_id*."""
        if entity_id not in self._pending:
            # First event in this window → flush immediately (no extra latency)
            self._flush(entity_id)
            # Schedule a deferred flush to catch any rapid follow-on events
            self._pending[entity_id] = self._hass.loop.call_later(
                self._debounce, self._deferred_flush, entity_id
            )
        # else: subsequent event within debounce window → already scheduled, do nothing

    def _deferred_flush(self, entity_id: str) -> None:
        """Called by the loop timer after the debounce window expires."""
        self._pending.pop(entity_id, None)
        self._flush(entity_id)

    def _flush(self, entity_id: str) -> None:
        """Write HA state for every sensor that cares about *entity_id*."""
        for sensor in self._listeners.get(entity_id, set()):
            sensor.async_write_ha_state()


# ---------------------------------------------------------------------------
# Base sensor class
# ---------------------------------------------------------------------------

class BelgiumEnergyCostSensor(SensorEntity):
    """Base class for Belgium Energy Cost sensors.

    Subclasses declare which *source* HA entity IDs they depend on via
    ``_source_entities()``.  The shared ``_UpdateThrottle`` takes care of
    subscribing, debouncing, and batch-writing state updates.
    """

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict,
        entry_id: str,
        throttle: _UpdateThrottle,
    ) -> None:
        self.hass = hass
        self._config = config
        self._entry_id = entry_id
        self._throttle = throttle
        self._contract_start: date = config[CONF_CONTRACT_START_DATE]
        # ENGIE sensor entity IDs — user-selected during setup, stored in config
        self._engie_peak = config.get(CONF_ENGIE_ELEC_PEAK, "")
        self._engie_offpeak = config.get(CONF_ENGIE_ELEC_OFFPEAK, "")
        self._engie_injection = config.get(CONF_ENGIE_ELEC_INJECTION, "")
        self._engie_gas = config.get(CONF_ENGIE_GAS, "")

    # ------------------------------------------------------------------
    # Subclass API
    # ------------------------------------------------------------------

    def _source_entities(self) -> list[str]:
        """Return the raw HA entity IDs this sensor depends on.

        The throttle subscribes to exactly these entities (deduplicating across
        sensors that share the same source).  Override in every subclass.
        """
        return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_state_value(self, entity_id: str, default: float = 0.0) -> float:
        """Return the numeric state of a HA entity, or *default* on failure."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return default
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return default

    def _calculate_months_since_start(self) -> float:
        """Months elapsed since the contract start date."""
        start_dt = datetime.combine(self._contract_start, time.min)
        start_ts = dt_util.as_timestamp(dt_util.as_local(start_dt))
        now_ts = dt_util.as_timestamp(dt_util.now())
        days = (now_ts - start_ts) / 86_400
        return round(days / DEFAULT_DAYS_PER_MONTH, 2)

    def _uid(self, suffix: str) -> str:
        """Config-entry-scoped unique ID."""
        return f"{DOMAIN}_{self._entry_id}_{suffix}"

    @property
    def suggested_display_precision(self) -> int | None:
        """Default display precision, driven by the sensor's unit.

        Currency amounts (EUR) always show two decimals; per-kWh prices keep
        five so sub-cent rates stay meaningful. Any other unit (kWh, m³) is
        left to Home Assistant's own default. A manual per-entity override set
        in the UI still takes priority over this suggestion.
        """
        unit = self.native_unit_of_measurement
        if unit == CURRENCY_EURO:
            return 2
        if unit == f"{CURRENCY_EURO}/kWh":
            return 5
        return None

    # ------------------------------------------------------------------
    # HA lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Register with the shared throttle."""
        sources = self._source_entities()
        if sources:
            self._throttle.register(self, sources)

    async def async_will_remove_from_hass(self) -> None:
        """Deregister from the shared throttle."""
        self._throttle.unregister(self)


# ---------------------------------------------------------------------------
# Contract duration
# ---------------------------------------------------------------------------

class MonthsSinceContractStartSensor(BelgiumEnergyCostSensor):
    """Months elapsed since the contract start date.

    This sensor has no external source entity — its value changes with the
    passage of time.  HA will call ``async_write_ha_state`` for it whenever
    any sibling sensor triggers a batch flush, which is frequent enough for
    a monthly-resolution value.
    """

    def __init__(self, hass, config, entry_id, throttle):
        super().__init__(hass, config, entry_id, throttle)
        self._attr_name = "Months Since Contract Start"
        self._attr_unique_id = self._uid(SENSOR_MONTHS_SINCE_START)
        self._attr_icon = "mdi:calendar-clock"

    @property
    def native_value(self) -> float:
        return self._calculate_months_since_start()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        days = (dt_util.now().date() - self._contract_start).days
        return {
            "contract_start": self._contract_start.strftime("%B %d, %Y"),
            "days_elapsed": days,
        }


# ---------------------------------------------------------------------------
# Electricity price sensors  (ENGIE variable price + fixed components)
# ---------------------------------------------------------------------------

class _ElecPriceBase(BelgiumEnergyCostSensor):
    """Shared logic for per-kWh electricity price sensors."""

    _engie_sensor: str  # set by subclass

    def __init__(self, hass, config, entry_id, throttle, costs: dict) -> None:
        super().__init__(hass, config, entry_id, throttle)
        self._costs = costs
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/kWh"
        self._attr_device_class = SensorDeviceClass.MONETARY

    def _source_entities(self) -> list[str]:
        return []  # overridden by each subclass


class TotalElectricityCostPeakSensor(_ElecPriceBase):

    def __init__(self, hass, config, entry_id, throttle, costs):
        super().__init__(hass, config, entry_id, throttle, costs)
        self._attr_name = "Total Electricity Cost Peak"
        self._attr_unique_id = self._uid(SENSOR_TOTAL_ELEC_PEAK)
        self._attr_icon = "mdi:lightning-bolt"

    def _source_entities(self) -> list[str]:
        return [self._engie_peak]

    @property
    def native_value(self) -> float:
        energy = self._get_state_value(self._engie_peak)
        return round(
            energy
            + self._costs[COST_GREEN_CERT]
            + self._costs[COST_DIST_PEAK]
            + self._costs[COST_TRANSMISSION]
            + self._costs[COST_COTISATION]
            + self._costs[COST_ACCISE],
            5,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        energy = self._get_state_value(self._engie_peak)
        return {
            "breakdown": (
                f"Energy (ENGIE): {energy:.5f} EUR/kWh\n"
                f"Green cert: {self._costs[COST_GREEN_CERT]:.5f} EUR/kWh\n"
                f"Distribution: {self._costs[COST_DIST_PEAK]:.5f} EUR/kWh\n"
                f"Transmission: {self._costs[COST_TRANSMISSION]:.5f} EUR/kWh\n"
                f"Cotisation: {self._costs[COST_COTISATION]:.5f} EUR/kWh\n"
                f"Accise: {self._costs[COST_ACCISE]:.5f} EUR/kWh"
            ),
            "period": "Weekdays 7h–22h",
        }


class TotalElectricityCostOffPeakSensor(_ElecPriceBase):

    def __init__(self, hass, config, entry_id, throttle, costs):
        super().__init__(hass, config, entry_id, throttle, costs)
        self._attr_name = "Total Electricity Cost Off-Peak"
        self._attr_unique_id = self._uid(SENSOR_TOTAL_ELEC_OFFPEAK)
        self._attr_icon = "mdi:lightning-bolt-outline"

    def _source_entities(self) -> list[str]:
        return [self._engie_offpeak]

    @property
    def native_value(self) -> float:
        energy = self._get_state_value(self._engie_offpeak)
        return round(
            energy
            + self._costs[COST_GREEN_CERT]
            + self._costs[COST_DIST_OFFPEAK]
            + self._costs[COST_TRANSMISSION]
            + self._costs[COST_COTISATION]
            + self._costs[COST_ACCISE],
            5,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        energy = self._get_state_value(self._engie_offpeak)
        return {
            "breakdown": (
                f"Energy (ENGIE): {energy:.5f} EUR/kWh\n"
                f"Green cert: {self._costs[COST_GREEN_CERT]:.5f} EUR/kWh\n"
                f"Distribution: {self._costs[COST_DIST_OFFPEAK]:.5f} EUR/kWh\n"
                f"Transmission: {self._costs[COST_TRANSMISSION]:.5f} EUR/kWh\n"
                f"Cotisation: {self._costs[COST_COTISATION]:.5f} EUR/kWh\n"
                f"Accise: {self._costs[COST_ACCISE]:.5f} EUR/kWh"
            ),
            "period": "Nights (22h–7h) + Weekends + Holidays",
        }


class TotalElectricityCostSingleSensor(_ElecPriceBase):
    """Single-tariff total electricity cost per kWh."""

    def __init__(self, hass, config, entry_id, throttle, costs):
        super().__init__(hass, config, entry_id, throttle, costs)
        self._attr_name = "Total Electricity Cost"
        self._attr_unique_id = self._uid(SENSOR_TOTAL_ELEC_SINGLE)
        self._attr_icon = "mdi:lightning-bolt"

    def _source_entities(self) -> list[str]:
        return [self._engie_peak]  # single tariff uses peak price feed

    @property
    def native_value(self) -> float:
        energy = self._get_state_value(self._engie_peak)
        return round(
            energy
            + self._costs[COST_GREEN_CERT]
            + self._costs[COST_DIST_SINGLE]
            + self._costs[COST_TRANSMISSION]
            + self._costs[COST_COTISATION]
            + self._costs[COST_ACCISE],
            5,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        energy = self._get_state_value(self._engie_peak)
        return {
            "breakdown": (
                f"Energy (ENGIE): {energy:.5f} EUR/kWh\n"
                f"Green cert: {self._costs[COST_GREEN_CERT]:.5f} EUR/kWh\n"
                f"Distribution: {self._costs[COST_DIST_SINGLE]:.5f} EUR/kWh\n"
                f"Transmission: {self._costs[COST_TRANSMISSION]:.5f} EUR/kWh\n"
                f"Cotisation: {self._costs[COST_COTISATION]:.5f} EUR/kWh\n"
                f"Accise: {self._costs[COST_ACCISE]:.5f} EUR/kWh"
            ),
        }


class ElectricityPeakOffPeakSavingsSensor(BelgiumEnergyCostSensor):
    """Price difference between peak and off-peak tariffs (EUR/kWh)."""

    def __init__(self, hass, config, entry_id, throttle,
                 peak: TotalElectricityCostPeakSensor,
                 offpeak: TotalElectricityCostOffPeakSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._peak = peak
        self._offpeak = offpeak
        self._attr_name = "Electricity Peak vs Off-Peak Savings"
        self._attr_unique_id = self._uid(SENSOR_ELEC_PEAK_OFFPEAK_SAVINGS)
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/kWh"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:piggy-bank"

    def _source_entities(self) -> list[str]:
        return [self._engie_peak, self._engie_offpeak]

    @property
    def native_value(self) -> float:
        return round((self._peak.native_value or 0.0) - (self._offpeak.native_value or 0.0), 5)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"savings_per_100kwh": round((self.native_value or 0.0) * 100, 2)}


class TotalElectricityInjectionPriceSensor(BelgiumEnergyCostSensor):
    """What ENGIE pays per injected kWh (solar export price)."""

    def __init__(self, hass, config, entry_id, throttle):
        super().__init__(hass, config, entry_id, throttle)
        self._attr_name = "Total Electricity Injection Price"
        self._attr_unique_id = self._uid(SENSOR_TOTAL_ELEC_INJECTION)
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/kWh"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:solar-power"

    def _source_entities(self) -> list[str]:
        return [self._engie_injection]

    @property
    def native_value(self) -> float:
        return self._get_state_value(self._engie_injection)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"note": "What ENGIE pays you for solar injection"}


class TotalGasCostPerKwhSensor(BelgiumEnergyCostSensor):
    """Total gas cost per kWh (variable ENGIE price + fixed per-kWh components)."""

    def __init__(self, hass, config, entry_id, throttle, costs: dict):
        super().__init__(hass, config, entry_id, throttle)
        self._costs = costs
        self._attr_name = "Total Gas Cost"
        self._attr_unique_id = self._uid(SENSOR_TOTAL_GAS)
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/kWh"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:fire"

    def _source_entities(self) -> list[str]:
        return [self._engie_gas]

    @property
    def native_value(self) -> float:
        energy = self._get_state_value(self._engie_gas)
        return round(
            energy
            + self._costs[COST_GAS_DISTRIBUTION]
            + self._costs[COST_GAS_TRANSMISSION]
            + self._costs[COST_GAS_COTISATION]
            + self._costs[COST_GAS_ACCISE],
            5,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        energy = self._get_state_value(self._engie_gas)
        return {
            "breakdown": (
                f"Energy (ENGIE): {energy:.5f} EUR/kWh\n"
                f"Distribution: {self._costs[COST_GAS_DISTRIBUTION]:.5f} EUR/kWh\n"
                f"Transmission: {self._costs[COST_GAS_TRANSMISSION]:.5f} EUR/kWh\n"
                f"Cotisation: {self._costs[COST_GAS_COTISATION]:.5f} EUR/kWh\n"
                f"Accise: {self._costs[COST_GAS_ACCISE]:.5f} EUR/kWh"
            ),
        }


# ---------------------------------------------------------------------------
# P1 consumption sensors
# ---------------------------------------------------------------------------

class _P1ConsumptionBase(BelgiumEnergyCostSensor):
    """Shared logic for P1-meter-based consumption sensors."""

    def __init__(self, hass, config, entry_id, throttle,
                 p1_entity: str, baseline: float) -> None:
        super().__init__(hass, config, entry_id, throttle)
        self._p1_entity = p1_entity
        self._baseline = baseline
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL

    def _source_entities(self) -> list[str]:
        return [self._p1_entity]

    @property
    def native_value(self) -> float:
        # Use baseline as default so unavailable P1 sensor returns 0, not negative
        current = self._get_state_value(self._p1_entity, self._baseline)
        return round(max(0.0, current - self._baseline), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        current = self._get_state_value(self._p1_entity, self._baseline)
        return {
            "current_reading": f"{current:.2f} kWh",
            "baseline_reading": f"{self._baseline:.2f} kWh",
        }


class ElectricityPeakConsumptionSensor(_P1ConsumptionBase):
    def __init__(self, hass, config, entry_id, throttle, import_config):
        super().__init__(
            hass, config, entry_id, throttle,
            import_config[CONF_P1_SENSORS][SENSOR_PEAK],
            import_config[CONF_BASELINE_READINGS][SENSOR_PEAK],
        )
        self._attr_name = "Electricity Peak Consumption Since Contract Start"
        self._attr_unique_id = self._uid(SENSOR_ELEC_PEAK_CONSUMPTION)
        self._attr_icon = "mdi:lightning-bolt"


class ElectricityOffPeakConsumptionSensor(_P1ConsumptionBase):
    def __init__(self, hass, config, entry_id, throttle, import_config):
        super().__init__(
            hass, config, entry_id, throttle,
            import_config[CONF_P1_SENSORS][SENSOR_OFFPEAK],
            import_config[CONF_BASELINE_READINGS][SENSOR_OFFPEAK],
        )
        self._attr_name = "Electricity Off-Peak Consumption Since Contract Start"
        self._attr_unique_id = self._uid(SENSOR_ELEC_OFFPEAK_CONSUMPTION)
        self._attr_icon = "mdi:lightning-bolt-outline"


class ElectricitySingleConsumptionSensor(_P1ConsumptionBase):
    def __init__(self, hass, config, entry_id, throttle, import_config):
        super().__init__(
            hass, config, entry_id, throttle,
            import_config[CONF_P1_SENSORS][SENSOR_TOTAL],
            import_config[CONF_BASELINE_READINGS][SENSOR_TOTAL],
        )
        self._attr_name = "Electricity Consumption Since Contract Start"
        self._attr_unique_id = self._uid(SENSOR_ELEC_SINGLE_CONSUMPTION)
        self._attr_icon = "mdi:lightning-bolt"


# ---------------------------------------------------------------------------
# Solar export sensors
# ---------------------------------------------------------------------------

class ElectricityExportTotalSensor(BelgiumEnergyCostSensor):
    """Total kWh injected to the grid since contract start."""

    def __init__(self, hass, config, entry_id, throttle, export_config: dict):
        super().__init__(hass, config, entry_id, throttle)
        p1 = export_config[CONF_P1_SENSORS]
        bl = export_config[CONF_BASELINE_READINGS]
        self._sensors: list[tuple[str, float]] = (
            [(p1[SENSOR_TOTAL], bl[SENSOR_TOTAL])]
            if SENSOR_TOTAL in p1
            else [
                (p1[SENSOR_PEAK], bl[SENSOR_PEAK]),
                (p1[SENSOR_OFFPEAK], bl[SENSOR_OFFPEAK]),
            ]
        )
        self._attr_name = "Electricity Total Export Since Contract Start"
        self._attr_unique_id = self._uid(SENSOR_ELEC_EXPORT_TOTAL)
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:solar-power"

    def _source_entities(self) -> list[str]:
        return [entity for entity, _ in self._sensors]

    @property
    def native_value(self) -> float:
        return round(
            sum(self._get_state_value(e) - bl for e, bl in self._sensors), 2
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        for i, (entity, baseline) in enumerate(self._sensors):
            label = "" if len(self._sensors) == 1 else f"_{i}"
            attrs[f"current_reading{label}"] = f"{self._get_state_value(entity):.2f} kWh"
            attrs[f"baseline_reading{label}"] = f"{baseline:.2f} kWh"
        return attrs


class ElectricityExportRevenueSensor(BelgiumEnergyCostSensor):
    """Total revenue earned from solar injection since contract start."""

    def __init__(self, hass, config, entry_id, throttle,
                 export_total: ElectricityExportTotalSensor,
                 injection_price: TotalElectricityInjectionPriceSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._export_total = export_total
        self._injection_price = injection_price
        self._attr_name = "Electricity Injection Revenue Since Contract Start"
        self._attr_unique_id = self._uid(SENSOR_ELEC_EXPORT_REVENUE)
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:cash-plus"

    def _source_entities(self) -> list[str]:
        return [self._engie_injection] + self._export_total._source_entities()

    @property
    def native_value(self) -> float:
        return round(
            (self._export_total.native_value or 0.0)
            * (self._injection_price.native_value or 0.0),
            2,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "export_kwh": f"{self._export_total.native_value or 0:.2f} kWh",
            "injection_price": f"{self._injection_price.native_value or 0:.5f} EUR/kWh",
        }


# ---------------------------------------------------------------------------
# Electricity cost accumulation
# ---------------------------------------------------------------------------

class ElectricityTotalCostSensor(BelgiumEnergyCostSensor):
    """Total electricity cost (energy + fixed monthly) since contract start."""

    def __init__(self, hass, config, entry_id, throttle,
                 meter_type: str, costs: dict,
                 peak_consumption: ElectricityPeakConsumptionSensor | None,
                 offpeak_consumption: ElectricityOffPeakConsumptionSensor | None,
                 single_consumption: ElectricitySingleConsumptionSensor | None,
                 peak_price: TotalElectricityCostPeakSensor | None,
                 offpeak_price: TotalElectricityCostOffPeakSensor | None,
                 single_price: TotalElectricityCostSingleSensor | None):
        super().__init__(hass, config, entry_id, throttle)
        self._meter_type = meter_type
        self._costs = costs
        self._peak_consumption = peak_consumption
        self._offpeak_consumption = offpeak_consumption
        self._single_consumption = single_consumption
        self._peak_price = peak_price
        self._offpeak_price = offpeak_price
        self._single_price = single_price
        self._attr_name = "Electricity Total Cost Since Contract Start"
        self._attr_unique_id = self._uid(SENSOR_ELEC_TOTAL_COST)
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:lightning-bolt-circle"

    def _source_entities(self) -> list[str]:
        if self._meter_type == METER_TYPE_BI_HORAIRE:
            return [
                self._peak_consumption._p1_entity,
                self._offpeak_consumption._p1_entity,
                self._engie_peak,
                self._engie_offpeak,
            ]
        return [self._single_consumption._p1_entity, self._engie_peak]

    @property
    def native_value(self) -> float:
        months = self._calculate_months_since_start()
        fixed = months * self._costs[COST_FIXED_MONTHLY]
        if self._meter_type == METER_TYPE_BI_HORAIRE:
            energy = (
                (self._peak_consumption.native_value or 0.0) * (self._peak_price.native_value or 0.0)
                + (self._offpeak_consumption.native_value or 0.0) * (self._offpeak_price.native_value or 0.0)
            )
        else:
            energy = (
                (self._single_consumption.native_value or 0.0) * (self._single_price.native_value or 0.0)
            )
        return round(energy + fixed, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        months = self._calculate_months_since_start()
        fixed = months * self._costs[COST_FIXED_MONTHLY]
        attrs: dict[str, Any] = {
            "fixed_costs": f"{fixed:.2f} EUR ({months} months)",
            "period": (
                f"{self._contract_start.strftime('%B %Y')} – "
                f"{dt_util.now().strftime('%B %Y')}"
            ),
        }
        if self._meter_type == METER_TYPE_BI_HORAIRE:
            pk = self._peak_consumption.native_value or 0.0
            op = self._offpeak_consumption.native_value or 0.0
            pkr = self._peak_price.native_value or 0.0
            opr = self._offpeak_price.native_value or 0.0
            attrs.update({
                "peak_consumption": f"{pk:.2f} kWh",
                "offpeak_consumption": f"{op:.2f} kWh",
                "peak_cost": f"{pk * pkr:.2f} EUR",
                "offpeak_cost": f"{op * opr:.2f} EUR",
            })
        else:
            attrs["consumption"] = f"{self._single_consumption.native_value or 0:.2f} kWh"
        return attrs


class ElectricityNetCostSensor(BelgiumEnergyCostSensor):
    """Net electricity cost = consumption cost minus solar injection revenue."""

    def __init__(self, hass, config, entry_id, throttle,
                 total_cost: ElectricityTotalCostSensor,
                 export_revenue: ElectricityExportRevenueSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._total_cost = total_cost
        self._export_revenue = export_revenue
        self._attr_name = "Electricity Net Cost Since Contract Start"
        self._attr_unique_id = self._uid(SENSOR_ELEC_NET_COST)
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:cash-minus"

    def _source_entities(self) -> list[str]:
        return list(set(
            self._total_cost._source_entities()
            + self._export_revenue._source_entities()
        ))

    @property
    def native_value(self) -> float:
        return round(
            (self._total_cost.native_value or 0.0)
            - (self._export_revenue.native_value or 0.0),
            2,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "consumption_cost": f"{self._total_cost.native_value or 0:.2f} EUR",
            "injection_revenue": f"{self._export_revenue.native_value or 0:.2f} EUR",
        }


class ElectricityAnnualCostSensor(BelgiumEnergyCostSensor):
    """Annualised electricity cost extrapolated from consumption to date."""

    def __init__(self, hass, config, entry_id, throttle,
                 total_cost: ElectricityTotalCostSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._total_cost = total_cost
        self._attr_name = "Electricity Estimated Annual Cost"
        self._attr_unique_id = self._uid(SENSOR_ELEC_ANNUAL_COST)
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:calendar-lightning"

    def _source_entities(self) -> list[str]:
        return self._total_cost._source_entities()

    @property
    def native_value(self) -> float:
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0.0
        return round((self._total_cost.native_value or 0.0) / months * 12, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        months = self._calculate_months_since_start()
        if months > 0:
            return {"monthly_average": f"{(self._total_cost.native_value or 0) / months:.2f} EUR/month"}
        return {}


class ElectricityAnnualRevenueSensor(BelgiumEnergyCostSensor):
    """Annualised solar injection revenue."""

    def __init__(self, hass, config, entry_id, throttle,
                 export_revenue: ElectricityExportRevenueSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._export_revenue = export_revenue
        self._attr_name = "Electricity Estimated Annual Injection Revenue"
        self._attr_unique_id = self._uid(SENSOR_ELEC_ANNUAL_REVENUE)
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:solar-power-variant"

    def _source_entities(self) -> list[str]:
        return self._export_revenue._source_entities()

    @property
    def native_value(self) -> float:
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0.0
        return round((self._export_revenue.native_value or 0.0) / months * 12, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        months = self._calculate_months_since_start()
        if months > 0:
            return {"monthly_average": f"{(self._export_revenue.native_value or 0) / months:.2f} EUR/month"}
        return {}


# ---------------------------------------------------------------------------
# Electricity monthly averages
# ---------------------------------------------------------------------------

class ElectricityAverageMonthlyConsumptionSensor(BelgiumEnergyCostSensor):
    def __init__(self, hass, config, entry_id, throttle, meter_type: str,
                 peak: ElectricityPeakConsumptionSensor | None,
                 offpeak: ElectricityOffPeakConsumptionSensor | None,
                 single: ElectricitySingleConsumptionSensor | None):
        super().__init__(hass, config, entry_id, throttle)
        self._meter_type = meter_type
        self._peak = peak
        self._offpeak = offpeak
        self._single = single
        self._attr_name = "Electricity Average Monthly Consumption"
        self._attr_unique_id = self._uid("electricity_avg_monthly_consumption")
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_icon = "mdi:calendar-month"

    def _source_entities(self) -> list[str]:
        if self._meter_type == METER_TYPE_BI_HORAIRE:
            return [self._peak._p1_entity, self._offpeak._p1_entity]
        return [self._single._p1_entity]

    @property
    def native_value(self) -> float:
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0.0
        total = (
            (self._peak.native_value or 0.0) + (self._offpeak.native_value or 0.0)
            if self._meter_type == METER_TYPE_BI_HORAIRE
            else (self._single.native_value or 0.0)
        )
        return round(total / months, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        months = self._calculate_months_since_start()
        if self._meter_type == METER_TYPE_BI_HORAIRE and months > 0:
            return {
                "peak_avg_monthly": f"{(self._peak.native_value or 0) / months:.2f} kWh/month",
                "offpeak_avg_monthly": f"{(self._offpeak.native_value or 0) / months:.2f} kWh/month",
                "months_elapsed": months,
            }
        return {"months_elapsed": months}


class ElectricityAverageMonthlyCostSensor(BelgiumEnergyCostSensor):
    def __init__(self, hass, config, entry_id, throttle,
                 total_cost: ElectricityTotalCostSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._total_cost = total_cost
        self._attr_name = "Electricity Average Monthly Cost"
        self._attr_unique_id = self._uid("electricity_avg_monthly_cost")
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:calendar-cash"

    def _source_entities(self) -> list[str]:
        return self._total_cost._source_entities()

    @property
    def native_value(self) -> float:
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0.0
        return round((self._total_cost.native_value or 0.0) / months, 2)


# ---------------------------------------------------------------------------
# Gas sensors
# ---------------------------------------------------------------------------

class _GasSensorBase(BelgiumEnergyCostSensor):
    """Base for gas sensors — uses the gas contract start date for month calculations."""
    def __init__(self, hass, config, entry_id, throttle):
        super().__init__(hass, config, entry_id, throttle)
        # Override contract start with the gas-specific date if available
        gas_cfg = config.get(CONF_GAS, {})
        if CONF_CONTRACT_START_DATE in gas_cfg:
            self._contract_start = gas_cfg[CONF_CONTRACT_START_DATE]


class GasConsumptionSensor(_GasSensorBase):
    """Gas consumption since contract start in m³."""

    def __init__(self, hass, config, entry_id, throttle):
        super().__init__(hass, config, entry_id, throttle)
        self._baseline_m3: float = config[CONF_GAS][CONF_BASELINE_READING_M3]
        self._gas_meter_entity = get_gas_meter_entity_id(entry_id)
        self._attr_name = "Gas Consumption Since Contract Start"
        self._attr_unique_id = self._uid("gas_consumption_m3")
        self._attr_native_unit_of_measurement = "m³"
        self._attr_device_class = SensorDeviceClass.GAS
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:meter-gas"

    def _source_entities(self) -> list[str]:
        return [self._gas_meter_entity]

    @property
    def native_value(self) -> float:
        current = self._get_state_value(self._gas_meter_entity, self._baseline_m3)
        # Guard: if the number entity hasn't restored yet it returns 0, which
        # would produce a large negative consumption.  Clamp to >= 0.
        return round(max(0.0, current - self._baseline_m3), 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        current = self._get_state_value(self._gas_meter_entity, self._baseline_m3)
        return {
            "current_reading": f"{current:.3f} m³",
            "baseline_reading": f"{self._baseline_m3:.3f} m³",
        }


class GasConsumptionKwhSensor(_GasSensorBase):
    """Gas consumption since contract start in kWh."""

    def __init__(self, hass, config, entry_id, throttle,
                 consumption_m3: GasConsumptionSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._consumption_m3 = consumption_m3
        self._conversion: float = config[CONF_GAS][CONF_CONVERSION_FACTOR]
        self._attr_name = "Gas Consumption Since Contract Start (kWh)"
        self._attr_unique_id = self._uid("gas_consumption_kwh")
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:fire"

    def _source_entities(self) -> list[str]:
        return self._consumption_m3._source_entities()

    @property
    def native_value(self) -> float:
        return round((self._consumption_m3.native_value or 0.0) * self._conversion, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "consumption_m3": f"{self._consumption_m3.native_value or 0:.3f} m³",
            "conversion_factor": f"{self._conversion} kWh/m³",
        }


class GasTotalCostSensor(_GasSensorBase):
    """Total gas cost (energy + fixed monthly) since contract start in EUR."""

    def __init__(self, hass, config, entry_id, throttle,
                 costs: dict,
                 consumption_kwh: GasConsumptionKwhSensor,
                 gas_price: TotalGasCostPerKwhSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._costs = costs
        self._consumption_kwh = consumption_kwh
        self._gas_price = gas_price
        self._attr_name = "Gas Total Cost Since Contract Start"
        self._attr_unique_id = self._uid(SENSOR_GAS_TOTAL_COST)
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:fire-circle"

    def _source_entities(self) -> list[str]:
        return list(set(
            self._consumption_kwh._source_entities()
            + self._gas_price._source_entities()
        ))

    @property
    def native_value(self) -> float:
        energy_cost = (
            (self._consumption_kwh.native_value or 0.0)
            * (self._gas_price.native_value or 0.0)
        )
        fixed = self._calculate_months_since_start() * self._costs[COST_GAS_FIXED_MONTHLY]
        return round(energy_cost + fixed, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        kwh = self._consumption_kwh.native_value or 0.0
        rate = self._gas_price.native_value or 0.0
        months = self._calculate_months_since_start()
        fixed = months * self._costs[COST_GAS_FIXED_MONTHLY]
        return {
            "consumption_kwh": f"{kwh:.2f} kWh",
            "consumption_m3": f"{self._consumption_kwh._consumption_m3.native_value or 0:.3f} m³",
            "energy_costs": f"{kwh * rate:.2f} EUR",
            "fixed_costs": f"{fixed:.2f} EUR ({months} months)",
            "cost_per_kwh": f"{rate:.5f} EUR/kWh",
            "period": (
                f"{self._contract_start.strftime('%B %Y')} – "
                f"{dt_util.now().strftime('%B %Y')}"
            ),
        }


class GasAnnualCostSensor(_GasSensorBase):
    def __init__(self, hass, config, entry_id, throttle,
                 gas_total: GasTotalCostSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._gas_total = gas_total
        self._attr_name = "Gas Estimated Annual Cost"
        self._attr_unique_id = self._uid(SENSOR_GAS_ANNUAL_COST)
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:calendar-fire"

    def _source_entities(self) -> list[str]:
        return self._gas_total._source_entities()

    @property
    def native_value(self) -> float:
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0.0
        return round((self._gas_total.native_value or 0.0) / months * 12, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        months = self._calculate_months_since_start()
        if months > 0:
            monthly = (self._gas_total.native_value or 0.0) / months
            fixed_annual = self._gas_total._costs[COST_GAS_FIXED_MONTHLY] * 12
            return {
                "monthly_average": f"{monthly:.2f} EUR/month",
                "fixed_cost_annual": f"{fixed_annual:.2f} EUR/year",
            }
        return {}


class GasAverageMonthlyConsumptionSensor(_GasSensorBase):
    def __init__(self, hass, config, entry_id, throttle,
                 consumption_kwh: GasConsumptionKwhSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._consumption_kwh = consumption_kwh
        self._attr_name = "Gas Average Monthly Consumption"
        self._attr_unique_id = self._uid("gas_avg_monthly_consumption")
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_icon = "mdi:calendar-month"

    def _source_entities(self) -> list[str]:
        return self._consumption_kwh._source_entities()

    @property
    def native_value(self) -> float:
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0.0
        return round((self._consumption_kwh.native_value or 0.0) / months, 2)


class GasAverageMonthlyCostSensor(_GasSensorBase):
    def __init__(self, hass, config, entry_id, throttle,
                 gas_total: GasTotalCostSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._gas_total = gas_total
        self._attr_name = "Gas Average Monthly Cost"
        self._attr_unique_id = self._uid("gas_avg_monthly_cost")
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:calendar-cash"

    def _source_entities(self) -> list[str]:
        return self._gas_total._source_entities()

    @property
    def native_value(self) -> float:
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0.0
        return round((self._gas_total.native_value or 0.0) / months, 2)


# ---------------------------------------------------------------------------
# Combined totals
# ---------------------------------------------------------------------------

class TotalEnergyCostSensor(BelgiumEnergyCostSensor):
    def __init__(self, hass, config, entry_id, throttle,
                 elec_total: ElectricityTotalCostSensor,
                 gas_total: GasTotalCostSensor | None):
        super().__init__(hass, config, entry_id, throttle)
        self._elec_total = elec_total
        self._gas_total = gas_total
        self._attr_name = "Total Energy Cost Since Contract Start"
        self._attr_unique_id = self._uid(SENSOR_TOTAL_ENERGY_COST)
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:cash-multiple"

    def _source_entities(self) -> list[str]:
        entities = list(self._elec_total._source_entities())
        if self._gas_total:
            entities += self._gas_total._source_entities()
        return list(set(entities))

    @property
    def native_value(self) -> float:
        gas = (self._gas_total.native_value or 0.0) if self._gas_total else 0.0
        return round((self._elec_total.native_value or 0.0) + gas, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        months = self._calculate_months_since_start()
        attrs: dict[str, Any] = {
            "electricity_cost": f"{self._elec_total.native_value or 0:.2f} EUR",
            "period": (
                f"{self._contract_start.strftime('%B %Y')} – "
                f"{dt_util.now().strftime('%B %Y')} ({months} months)"
            ),
        }
        if self._gas_total:
            attrs["gas_cost"] = f"{self._gas_total.native_value or 0:.2f} EUR"
        return attrs


class TotalAnnualEnergyCostSensor(BelgiumEnergyCostSensor):
    def __init__(self, hass, config, entry_id, throttle,
                 elec_annual: ElectricityAnnualCostSensor,
                 gas_annual: GasAnnualCostSensor | None):
        super().__init__(hass, config, entry_id, throttle)
        self._elec_annual = elec_annual
        self._gas_annual = gas_annual
        self._attr_name = "Total Estimated Annual Energy Cost"
        self._attr_unique_id = self._uid(SENSOR_TOTAL_ANNUAL_COST)
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:cash-clock"

    def _source_entities(self) -> list[str]:
        entities = list(self._elec_annual._source_entities())
        if self._gas_annual:
            entities += self._gas_annual._source_entities()
        return list(set(entities))

    @property
    def native_value(self) -> float:
        gas = (self._gas_annual.native_value or 0.0) if self._gas_annual else 0.0
        return round((self._elec_annual.native_value or 0.0) + gas, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        total = self.native_value or 0.0
        attrs: dict[str, Any] = {
            "electricity_annual": f"{self._elec_annual.native_value or 0:.0f} EUR/year",
            "monthly_average": f"{total / 12:.2f} EUR/month",
        }
        if self._gas_annual:
            attrs["gas_annual"] = f"{self._gas_annual.native_value or 0:.0f} EUR/year"
        return attrs


class TotalAverageMonthlyEnergyCostSensor(BelgiumEnergyCostSensor):
    def __init__(self, hass, config, entry_id, throttle,
                 total_cost: TotalEnergyCostSensor):
        super().__init__(hass, config, entry_id, throttle)
        self._total_cost = total_cost
        self._attr_name = "Total Average Monthly Energy Cost"
        self._attr_unique_id = self._uid("total_avg_monthly_cost")
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:calendar-fire"

    def _source_entities(self) -> list[str]:
        return self._total_cost._source_entities()

    @property
    def native_value(self) -> float:
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0.0
        return round((self._total_cost.native_value or 0.0) / months, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        months = self._calculate_months_since_start()
        elec_v = self._total_cost._elec_total.native_value or 0.0
        attrs: dict[str, Any] = {
            "electricity_monthly": f"{elec_v / months:.2f} EUR/month" if months > 0 else "N/A",
            "months_elapsed": months,
        }
        if self._total_cost._gas_total:
            gas_v = self._total_cost._gas_total.native_value or 0.0
            attrs["gas_monthly"] = f"{gas_v / months:.2f} EUR/month" if months > 0 else "N/A"
        return attrs


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-contract-year history sensors (additive; never affect the core sensors)
# ---------------------------------------------------------------------------

class _YearHistoryBase(BelgiumEnergyCostSensor):
    """Shared base for contract-year sensors.

    ``cumulative_metrics`` maps a stable key → the lifetime (since-contract-start)
    consumption sensor for that metric. These are *stable* quantities (kWh, m³),
    so current-year consumption = lifetime − last close cumulative.
    """

    def __init__(self, hass, config, entry_id, throttle, *,
                 utility: str, start: date, history: ContractYearHistory,
                 cumulative_metrics: dict[str, "BelgiumEnergyCostSensor"],
                 price_sensors: list["BelgiumEnergyCostSensor"] | None = None) -> None:
        super().__init__(hass, config, entry_id, throttle)
        self._utility = utility
        self._start = start
        self._history = history
        self._cumulative_metrics = cumulative_metrics
        # Price sensors whose value feeds cost_fn. The current-period cost must
        # recompute when these change, not only when consumption ticks — else it
        # goes stale between P1 updates while the ENGIE price moves.
        self._price_sensors = price_sensors or []

    def _source_entities(self) -> list[str]:
        srcs: list[str] = []
        for s in self._cumulative_metrics.values():
            srcs += s._source_entities()
        for s in self._price_sensors:
            srcs += s._source_entities()
        return list(set(srcs))

    def _current_year_consumption(self) -> dict[str, float]:
        """Current-year consumption deltas (lifetime − last close cumulative)."""
        base = self._history.last_cumulative(self._utility)
        out = {}
        for k, s in self._cumulative_metrics.items():
            lifetime = float(s.native_value or 0.0)
            out[k] = max(0.0, lifetime - base.get(k, 0.0))
        return out


class ContractYearCurrentSensor(_YearHistoryBase):
    """Cost accumulated in the *current* (in-progress) contract year (EUR).

    Computed LIVE from current-year consumption × current price + elapsed-month
    fixed cost — NOT as a lifetime-cost delta (which would drift as prices move
    and re-price prior years). ``cost_fn`` takes the current-year consumption
    dict and the months elapsed in the current year and returns EUR.
    """

    def __init__(self, hass, config, entry_id, throttle, *, utility, start,
                 history, cumulative_metrics, cost_fn, name, uid, icon,
                 price_sensors=None):
        super().__init__(hass, config, entry_id, throttle,
                         utility=utility, start=start, history=history,
                         cumulative_metrics=cumulative_metrics,
                         price_sensors=price_sensors)
        self._cost_fn = cost_fn
        self._attr_name = name
        self._attr_unique_id = self._uid(uid)
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = icon

    def _months_into_current_year(self) -> float:
        """Months elapsed since the current period actually began.

        The current period begins where the *last close ended* (its
        period_end), because consumption is measured by meter deltas captured at
        that close. This keeps periods contiguous: if a period was closed early
        (meter read before the anniversary), the days between the reading and the
        anniversary fall into the new period rather than being dropped. With no
        prior close, the period begins at the contract start date.
        """
        last_end = self._history.last_period_end(self._utility)
        if last_end is not None:
            year_start = last_end
        else:
            year_start = self._start
        today = dt_util.now().date()
        if today < year_start:
            return 0.0
        days = (today - year_start).days
        return days / DEFAULT_DAYS_PER_MONTH

    @property
    def native_value(self) -> float:
        cons = self._current_year_consumption()
        months = self._months_into_current_year()
        return round(max(0.0, self._cost_fn(cons, months)), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        idx = self._history.completed_year_count(self._utility) + 1
        cons = self._current_year_consumption()
        attrs = {
            "contract_year": contract_year_label(self._start, idx),
            "year_index": idx,
            "completed_years_stored": self._history.completed_year_count(self._utility),
        }
        for k, v in cons.items():
            attrs[f"current_year_{k}"] = round(v, 3)
        return attrs


class ContractYearHistorySensor(_YearHistoryBase):
    """Diagnostic sensor exposing every *closed* contract year in attributes.

    State = number of completed contract years on record.
    """

    _attr_state_class = None

    def __init__(self, hass, config, entry_id, throttle, *, utility, start,
                 history, cumulative_metrics, name: str, uid: str, icon: str):
        super().__init__(hass, config, entry_id, throttle,
                         utility=utility, start=start, history=history,
                         cumulative_metrics=cumulative_metrics)
        self._attr_name = name
        self._attr_unique_id = self._uid(uid)
        self._attr_icon = icon

    @property
    def native_value(self) -> int:
        return self._history.completed_year_count(self._utility)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "contract_start": self._start.isoformat(),
            "completed_years": self._history.completed_year_count(self._utility),
            "current_year": contract_year_label(
                self._start, self._history.completed_year_count(self._utility) + 1
            ),
            "years": self._history.closed_years(self._utility),
        }


class AccumulatedCostSensor(BelgiumEnergyCostSensor):
    """True running cost (EUR), accumulated at the price each kWh was used.

    On every consumption tick this adds ``Δkwh × current_price`` to a persisted
    total via ``CostAccumulator`` — so, unlike the lifetime "total cost" sensor,
    it does NOT re-price history when the ENGIE price moves. Accurate from the
    moment it starts running (it seeds its baseline from the current reading).

    ``streams`` maps a stable stream key → (consumption_sensor, price_sensor).
    Multiple streams (e.g. peak + off-peak) sum into one accumulated total.
    """

    _attr_native_unit_of_measurement = CURRENCY_EURO
    _attr_device_class = SensorDeviceClass.MONETARY
    # HA requires monetary sensors to use TOTAL (or None), not TOTAL_INCREASING.
    # The accumulated cost is a running total that only grows (re-seeding keeps
    # the total, just rebases the meter delta), so TOTAL is the correct class.
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, hass, config, entry_id, throttle, *, accumulator,
                 streams: dict, name: str, uid: str, icon: str):
        super().__init__(hass, config, entry_id, throttle)
        self._accumulator = accumulator
        self._streams = streams  # key -> (consumption_sensor, price_sensor)
        self._attr_name = name
        self._attr_unique_id = self._uid(uid)
        self._attr_icon = icon
        self._unsub = None

    def _source_entities(self) -> list[str]:
        srcs: list[str] = []
        for cons, _price in self._streams.values():
            srcs += cons._source_entities()
        return list(set(srcs))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Drive ticks on consumption changes via our own subscription. We do the
        # async accumulation here (not in native_value, which is sync), then
        # write state so the new total shows. Seed once on startup too.
        await self._tick_and_write()
        srcs = self._source_entities()
        if srcs:
            self._unsub = async_track_state_change_event(
                self.hass, srcs, self._on_consumption_change
            )

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _on_consumption_change(self, event) -> None:
        self.hass.async_create_task(self._tick_and_write())

    async def _tick_and_write(self) -> None:
        for key, (cons, price) in self._streams.items():
            kwh = cons.native_value
            pr = price.native_value
            if kwh is None or pr is None:
                continue
            try:
                await self._accumulator.async_tick(key, float(kwh), float(pr))
            except Exception:  # noqa: BLE001 - never let a tick break state writes
                _LOGGER.exception("cost accumulator tick failed for stream '%s'", key)
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return round(sum(self._accumulator.running_cost(k) for k in self._streams), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "note": "Accurate running cost — each kWh priced when consumed. "
                    "Accurate from when this sensor started; not retroactive.",
            **{f"{k}_eur": round(self._accumulator.running_cost(k), 2) for k in self._streams},
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Build and register all sensors for one config entry."""

    conf: dict = dict(entry.data)

    # Make ENGIE sensor IDs available at the top level of conf
    # (they are already stored there by _async_create_entry)

    # Parse per-utility contract start dates (stored as ISO strings in config entry).
    elec = dict(conf[CONF_ELECTRICITY])
    if isinstance(elec.get(CONF_CONTRACT_START_DATE), str):
        elec[CONF_CONTRACT_START_DATE] = datetime.fromisoformat(elec[CONF_CONTRACT_START_DATE]).date()
    conf[CONF_ELECTRICITY] = elec

    # Electricity contract date is the primary date used by most sensors.
    conf[CONF_CONTRACT_START_DATE] = elec[CONF_CONTRACT_START_DATE]

    if conf.get(CONF_GAS, {}).get(CONF_ENABLED, False):
        gas = dict(conf[CONF_GAS])
        if isinstance(gas.get(CONF_CONTRACT_START_DATE), str):
            gas[CONF_CONTRACT_START_DATE] = datetime.fromisoformat(gas[CONF_CONTRACT_START_DATE]).date()
        conf[CONF_GAS] = gas

    entry_id = entry.entry_id
    meter_type: str = conf[CONF_ELECTRICITY][CONF_METER_TYPE]
    elec_costs: dict = conf[CONF_ELECTRICITY][CONF_COSTS]
    elec_import: dict = conf[CONF_ELECTRICITY][CONF_IMPORT]
    elec_export: dict = conf[CONF_ELECTRICITY].get(CONF_EXPORT, {})
    has_solar: bool = elec_export.get(CONF_ENABLED, False)
    has_gas: bool = conf.get(CONF_GAS, {}).get(CONF_ENABLED, False)

    # One shared throttle per config entry.
    # It deduplicates subscriptions and batches state writes for all sensors.
    throttle = _UpdateThrottle(hass, DEBOUNCE_SECONDS)

    sensors: list[BelgiumEnergyCostSensor] = []

    # --- Contract duration (no external source; updated passively) ---
    sensors.append(MonthsSinceContractStartSensor(hass, conf, entry_id, throttle))

    # --- Electricity price sensors ---
    if meter_type == METER_TYPE_BI_HORAIRE:
        peak_price = TotalElectricityCostPeakSensor(hass, conf, entry_id, throttle, elec_costs)
        offpeak_price = TotalElectricityCostOffPeakSensor(hass, conf, entry_id, throttle, elec_costs)
        single_price = None
        sensors += [peak_price, offpeak_price]
        sensors.append(
            ElectricityPeakOffPeakSavingsSensor(hass, conf, entry_id, throttle, peak_price, offpeak_price)
        )
    else:
        peak_price = offpeak_price = None
        single_price = TotalElectricityCostSingleSensor(hass, conf, entry_id, throttle, elec_costs)
        sensors.append(single_price)

    # --- Consumption sensors ---
    if meter_type == METER_TYPE_BI_HORAIRE:
        peak_con = ElectricityPeakConsumptionSensor(hass, conf, entry_id, throttle, elec_import)
        offpeak_con = ElectricityOffPeakConsumptionSensor(hass, conf, entry_id, throttle, elec_import)
        single_con = None
        sensors += [peak_con, offpeak_con]
    else:
        peak_con = offpeak_con = None
        single_con = ElectricitySingleConsumptionSensor(hass, conf, entry_id, throttle, elec_import)
        sensors.append(single_con)

    # --- Solar export ---
    export_revenue: ElectricityExportRevenueSensor | None = None
    if has_solar:
        inj_price = TotalElectricityInjectionPriceSensor(hass, conf, entry_id, throttle)
        export_total = ElectricityExportTotalSensor(hass, conf, entry_id, throttle, elec_export)
        export_revenue = ElectricityExportRevenueSensor(hass, conf, entry_id, throttle, export_total, inj_price)
        sensors += [inj_price, export_total, export_revenue]

    # --- Electricity totals ---
    elec_total = ElectricityTotalCostSensor(
        hass, conf, entry_id, throttle, meter_type, elec_costs,
        peak_con, offpeak_con, single_con, peak_price, offpeak_price, single_price,
    )
    sensors.append(elec_total)

    if has_solar and export_revenue:
        sensors.append(ElectricityNetCostSensor(hass, conf, entry_id, throttle, elec_total, export_revenue))

    elec_annual = ElectricityAnnualCostSensor(hass, conf, entry_id, throttle, elec_total)
    sensors.append(elec_annual)

    if has_solar and export_revenue:
        sensors.append(ElectricityAnnualRevenueSensor(hass, conf, entry_id, throttle, export_revenue))

    sensors += [
        ElectricityAverageMonthlyConsumptionSensor(hass, conf, entry_id, throttle, meter_type, peak_con, offpeak_con, single_con),
        ElectricityAverageMonthlyCostSensor(hass, conf, entry_id, throttle, elec_total),
    ]

    # --- Gas ---
    gas_total: GasTotalCostSensor | None = None
    gas_annual: GasAnnualCostSensor | None = None
    if has_gas:
        gas_costs: dict = conf[CONF_GAS][CONF_COSTS]
        gas_price_kwh = TotalGasCostPerKwhSensor(hass, conf, entry_id, throttle, gas_costs)
        gas_con_m3 = GasConsumptionSensor(hass, conf, entry_id, throttle)
        gas_con_kwh = GasConsumptionKwhSensor(hass, conf, entry_id, throttle, gas_con_m3)
        gas_total = GasTotalCostSensor(hass, conf, entry_id, throttle, gas_costs, gas_con_kwh, gas_price_kwh)
        gas_annual = GasAnnualCostSensor(hass, conf, entry_id, throttle, gas_total)
        sensors += [
            gas_price_kwh, gas_con_m3, gas_con_kwh, gas_total, gas_annual,
            GasAverageMonthlyConsumptionSensor(hass, conf, entry_id, throttle, gas_con_kwh),
            GasAverageMonthlyCostSensor(hass, conf, entry_id, throttle, gas_total),
        ]

    # --- Combined ---
    total_energy = TotalEnergyCostSensor(hass, conf, entry_id, throttle, elec_total, gas_total)
    total_annual = TotalAnnualEnergyCostSensor(hass, conf, entry_id, throttle, elec_annual, gas_annual)
    sensors += [
        total_energy,
        total_annual,
        TotalAverageMonthlyEnergyCostSensor(hass, conf, entry_id, throttle, total_energy),
    ]

    # --- Per-contract-year history (ADDITIVE & FAIL-SAFE) -------------------
    # Wrapped so that any failure here can never prevent the core sensors above
    # from loading. Worst case: the year-history sensors are simply absent.
    #
    # KEY MODEL: per-year COST is computed from that year's own consumption ×
    # current price + elapsed-month fixed cost — NOT a lifetime-cost delta
    # (lifetime cost re-prices all history at the current price, so deltas drift
    # and would re-cost prior years whenever the ENGIE price moves). Closed-year
    # cost is FROZEN at close via the same cost function and never recomputed.
    try:
        history = ContractYearHistory(hass, entry_id)
        await history.async_load()

        # Cumulative (stable) consumption metrics — deltas give per-year usage.
        elec_metrics: dict[str, BelgiumEnergyCostSensor] = {}
        if meter_type == METER_TYPE_BI_HORAIRE:
            elec_metrics["peak_kwh"] = peak_con
            elec_metrics["offpeak_kwh"] = offpeak_con
        else:
            elec_metrics["kwh"] = single_con

        # Cost function: current-year electricity cost from consumption + months.
        def _elec_cost_fn(cons: dict, months: float) -> float:
            fixed = months * elec_costs[COST_FIXED_MONTHLY]
            if meter_type == METER_TYPE_BI_HORAIRE:
                energy = (
                    cons.get("peak_kwh", 0.0) * (peak_price.native_value or 0.0)
                    + cons.get("offpeak_kwh", 0.0) * (offpeak_price.native_value or 0.0)
                )
            else:
                energy = cons.get("kwh", 0.0) * (single_price.native_value or 0.0)
            return energy + fixed

        # Price sensors the elec cost depends on — current cost must refresh
        # when these change, not only on a P1 consumption tick.
        _elec_price_sensors = (
            [peak_price, offpeak_price] if meter_type == METER_TYPE_BI_HORAIRE
            else [single_price]
        )

        elec_start: date = conf[CONF_ELECTRICITY][CONF_CONTRACT_START_DATE]
        sensors += [
            ContractYearCurrentSensor(
                hass, conf, entry_id, throttle,
                utility=UTILITY_ELEC, start=elec_start, history=history,
                cumulative_metrics=elec_metrics, cost_fn=_elec_cost_fn,
                price_sensors=_elec_price_sensors,
                name="Electricity Cost This Billing Period",
                uid="electricity_cost_current_contract_year",
                icon="mdi:calendar-clock",
            ),
            ContractYearHistorySensor(
                hass, conf, entry_id, throttle,
                utility=UTILITY_ELEC, start=elec_start, history=history,
                cumulative_metrics=elec_metrics,
                name="Electricity Billing Period History",
                uid="electricity_contract_year_history",
                icon="mdi:history",
            ),
        ]

        # Defaults so the stash references below are always bound even when gas
        # is not configured. (_gas_cost_fn is redefined as a real function inside
        # the guard — the None default is intentional, not dead code.)
        gas_metrics = None
        _gas_cost_fn = None
        gas_start = None
        if has_gas and gas_total is not None:
            gas_metrics = {"kwh": gas_con_kwh, "m3": gas_con_m3}

            def _gas_cost_fn(cons: dict, months: float) -> float:
                fixed = months * gas_costs[COST_GAS_FIXED_MONTHLY]
                energy = cons.get("kwh", 0.0) * (gas_price_kwh.native_value or 0.0)
                return energy + fixed

            gas_start = conf[CONF_GAS].get(CONF_CONTRACT_START_DATE, elec_start)
            sensors += [
                ContractYearCurrentSensor(
                    hass, conf, entry_id, throttle,
                    utility=UTILITY_GAS, start=gas_start, history=history,
                    cumulative_metrics=gas_metrics, cost_fn=_gas_cost_fn,
                    price_sensors=[gas_price_kwh],
                    name="Gas Cost This Billing Period",
                    uid="gas_cost_current_contract_year",
                    icon="mdi:calendar-clock",
                ),
                ContractYearHistorySensor(
                    hass, conf, entry_id, throttle,
                    utility=UTILITY_GAS, start=gas_start, history=history,
                    cumulative_metrics=gas_metrics,
                    name="Gas Billing Period History",
                    uid="gas_contract_year_history",
                    icon="mdi:history",
                ),
            ]

        # Stash for the close/undo services (registered in __init__.py).
        # Each utility provides: start date, cumulative metrics (for the
        # lifetime values + per-year deltas), and a cost_fn to FREEZE the
        # year's cost at close.
        store = hass.data.setdefault(DOMAIN, {}).setdefault("_year_history", {})
        store[entry_id] = {
            "history": history,
            "elec": {"start": elec_start, "metrics": elec_metrics, "cost_fn": _elec_cost_fn},
        }
        if has_gas and gas_total is not None:
            store[entry_id]["gas"] = {
                "start": gas_start, "metrics": gas_metrics, "cost_fn": _gas_cost_fn,
            }
    except Exception:  # noqa: BLE001 - never let history break core sensors
        _LOGGER.exception(
            "Belgium Energy Costs: per-contract-year history failed to initialise; "
            "core sensors are unaffected"
        )

    # --- Continuous cost accumulator (ADDITIVE & FAIL-SAFE) -----------------
    # True running cost: each kWh priced when consumed (no re-pricing drift).
    # Accurate from first run; seeds its baseline from the current reading.
    try:
        from .cost_accumulator import CostAccumulator

        accumulator = CostAccumulator(hass, entry_id)
        await accumulator.async_load()

        # Electricity streams: (consumption_sensor, price_sensor) per tariff.
        if meter_type == METER_TYPE_BI_HORAIRE:
            elec_streams = {
                "elec_peak": (peak_con, peak_price),
                "elec_offpeak": (offpeak_con, offpeak_price),
            }
        else:
            elec_streams = {"elec": (single_con, single_price)}

        sensors.append(
            AccumulatedCostSensor(
                hass, conf, entry_id, throttle,
                accumulator=accumulator, streams=elec_streams,
                name="Electricity Cost Accumulated",
                uid="electricity_cost_accumulated",
                icon="mdi:cash-clock",
            )
        )

        if has_gas and gas_total is not None:
            gas_streams = {"gas": (gas_con_kwh, gas_price_kwh)}
            sensors.append(
                AccumulatedCostSensor(
                    hass, conf, entry_id, throttle,
                    accumulator=accumulator, streams=gas_streams,
                    name="Gas Cost Accumulated",
                    uid="gas_cost_accumulated",
                    icon="mdi:cash-clock",
                )
            )
    except Exception:  # noqa: BLE001 - never let the accumulator break core sensors
        _LOGGER.exception(
            "Belgium Energy Costs: cost accumulator failed to initialise; "
            "core sensors are unaffected"
        )

    async_add_entities(sensors, update_before_add=True)
