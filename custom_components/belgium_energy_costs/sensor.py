"""Sensor platform for Belgium Energy Costs."""
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant import config_entries
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfEnergy,
    CURRENCY_EURO,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
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
    GAS_METER_ENTITY_ID,
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
    ENGIE_SENSOR_ELEC_INJECTION,
    ENGIE_SENSOR_GAS,
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
)

_LOGGER = logging.getLogger(__name__)




class BelgiumEnergyCostSensor(SensorEntity):
    """Base class for Belgium Energy Cost sensors."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._config = config
        self._contract_start = config[CONF_CONTRACT_START_DATE]
        self._attr_should_poll = False
        
        # Debug logging
        _LOGGER.debug(
            "BelgiumEnergyCostSensor initialized with contract_start: %s (type: %s)",
            self._contract_start,
            type(self._contract_start).__name__
        )
        
    def _get_state_value(self, entity_id: str, default: float = 0.0) -> float:
        """Get state value as float."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return default
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return default
    
    def _calculate_months_since_start(self) -> float:
        """Calculate months since contract start."""
        start = datetime.combine(self._contract_start, datetime.min.time())
        start = dt_util.as_timestamp(start)
        today = dt_util.as_timestamp(dt_util.now())
        days = (today - start) / 86400
        return round(days / DEFAULT_DAYS_PER_MONTH, 1)


class MonthsSinceContractStartSensor(BelgiumEnergyCostSensor):
    """Sensor for months since contract start."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._attr_name = "Months Since Contract Start"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_MONTHS_SINCE_START}"
        self._attr_icon = "mdi:calendar-clock"
        
    @property
    def native_value(self) -> float:
        """Return the state."""
        return self._calculate_months_since_start()
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        start = datetime.combine(self._contract_start, datetime.min.time())
        days = (dt_util.now().date() - self._contract_start).days
        return {
            "contract_start": self._contract_start.strftime("%B %d, %Y"),
            "days_elapsed": days,
        }


class TotalElectricityCostPeakSensor(BelgiumEnergyCostSensor):
    """Sensor for total electricity cost at peak hours."""

    def __init__(self, hass: HomeAssistant, config: dict, costs: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._costs = costs
        self._attr_name = "Total Electricity Cost Peak"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_TOTAL_ELEC_PEAK}"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/kWh"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:lightning-bolt"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [ENGIE_SENSOR_ELEC_PEAK], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        energy = self._get_state_value(ENGIE_SENSOR_ELEC_PEAK)
        total = (
            energy +
            self._costs[COST_GREEN_CERT] +
            self._costs[COST_DIST_PEAK] +
            self._costs[COST_TRANSMISSION] +
            self._costs[COST_COTISATION] +
            self._costs[COST_ACCISE]
        )
        return round(total, 5)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        energy = self._get_state_value(ENGIE_SENSOR_ELEC_PEAK)
        return {
            "breakdown": (
                f"Energy (ENGIE): {energy:.5f} EUR/kWh\n"
                f"Green cert: {self._costs[COST_GREEN_CERT]:.5f} EUR/kWh\n"
                f"Distribution: {self._costs[COST_DIST_PEAK]:.5f} EUR/kWh\n"
                f"Transmission: {self._costs[COST_TRANSMISSION]:.5f} EUR/kWh\n"
                f"Cotisation: {self._costs[COST_COTISATION]:.5f} EUR/kWh\n"
                f"Accise: {self._costs[COST_ACCISE]:.5f} EUR/kWh"
            ),
            "period": "Weekdays 7h-22h"
        }


class TotalElectricityCostOffPeakSensor(BelgiumEnergyCostSensor):
    """Sensor for total electricity cost at off-peak hours."""

    def __init__(self, hass: HomeAssistant, config: dict, costs: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._costs = costs
        self._attr_name = "Total Electricity Cost Off-Peak"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_TOTAL_ELEC_OFFPEAK}"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/kWh"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:lightning-bolt-outline"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [ENGIE_SENSOR_ELEC_OFFPEAK], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        energy = self._get_state_value(ENGIE_SENSOR_ELEC_OFFPEAK)
        total = (
            energy +
            self._costs[COST_GREEN_CERT] +
            self._costs[COST_DIST_OFFPEAK] +
            self._costs[COST_TRANSMISSION] +
            self._costs[COST_COTISATION] +
            self._costs[COST_ACCISE]
        )
        return round(total, 5)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        energy = self._get_state_value(ENGIE_SENSOR_ELEC_OFFPEAK)
        return {
            "breakdown": (
                f"Energy (ENGIE): {energy:.5f} EUR/kWh\n"
                f"Green cert: {self._costs[COST_GREEN_CERT]:.5f} EUR/kWh\n"
                f"Distribution: {self._costs[COST_DIST_OFFPEAK]:.5f} EUR/kWh\n"
                f"Transmission: {self._costs[COST_TRANSMISSION]:.5f} EUR/kWh\n"
                f"Cotisation: {self._costs[COST_COTISATION]:.5f} EUR/kWh\n"
                f"Accise: {self._costs[COST_ACCISE]:.5f} EUR/kWh"
            ),
            "period": "Nights (22h-7h) + Weekends + Holidays"
        }


class TotalElectricityCostSingleSensor(BelgiumEnergyCostSensor):
    """Sensor for total electricity cost (single tariff)."""

    def __init__(self, hass: HomeAssistant, config: dict, costs: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._costs = costs
        self._attr_name = "Total Electricity Cost"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_TOTAL_ELEC_SINGLE}"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/kWh"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:lightning-bolt"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [ENGIE_SENSOR_ELEC_PEAK], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        energy = self._get_state_value(ENGIE_SENSOR_ELEC_PEAK)
        total = (
            energy +
            self._costs[COST_GREEN_CERT] +
            self._costs[COST_DIST_SINGLE] +
            self._costs[COST_TRANSMISSION] +
            self._costs[COST_COTISATION] +
            self._costs[COST_ACCISE]
        )
        return round(total, 5)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        energy = self._get_state_value(ENGIE_SENSOR_ELEC_PEAK)
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
    """Sensor for peak vs off-peak savings."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._attr_name = "Electricity Peak vs Off-Peak Savings"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_ELEC_PEAK_OFFPEAK_SAVINGS}"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/kWh"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:piggy-bank"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        peak_sensor = f"sensor.{SENSOR_TOTAL_ELEC_PEAK}"
        offpeak_sensor = f"sensor.{SENSOR_TOTAL_ELEC_OFFPEAK}"
        self._unsubscribe = async_track_state_change_event(
            self.hass, [peak_sensor, offpeak_sensor], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        peak = self._get_state_value(f"sensor.{SENSOR_TOTAL_ELEC_PEAK}")
        offpeak = self._get_state_value(f"sensor.{SENSOR_TOTAL_ELEC_OFFPEAK}")
        return round(peak - offpeak, 5)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        savings = self.native_value or 0
        return {
            "savings_per_100kwh": round(savings * 100, 2)
        }


class TotalElectricityInjectionPriceSensor(BelgiumEnergyCostSensor):
    """Sensor for solar injection price."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._attr_name = "Total Electricity Injection Price"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_TOTAL_ELEC_INJECTION}"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/kWh"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:solar-power"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [ENGIE_SENSOR_ELEC_INJECTION], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        return self._get_state_value(ENGIE_SENSOR_ELEC_INJECTION)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {
            "note": "What ENGIE pays you for solar injection"
        }


class TotalGasCostSensor(BelgiumEnergyCostSensor):
    """Sensor for total gas cost per kWh."""

    def __init__(self, hass: HomeAssistant, config: dict, costs: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._costs = costs
        self._attr_name = "Total Gas Cost"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_TOTAL_GAS}"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/kWh"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:fire"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [ENGIE_SENSOR_GAS], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        energy = self._get_state_value(ENGIE_SENSOR_GAS)
        total = (
            energy +
            self._costs[COST_GAS_DISTRIBUTION] +
            self._costs[COST_GAS_TRANSMISSION] +
            self._costs[COST_GAS_COTISATION] +
            self._costs[COST_GAS_ACCISE]
        )
        return round(total, 5)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        energy = self._get_state_value(ENGIE_SENSOR_GAS)
        return {
            "breakdown": (
                f"Energy (ENGIE): {energy:.5f} EUR/kWh\n"
                f"Distribution: {self._costs[COST_GAS_DISTRIBUTION]:.5f} EUR/kWh\n"
                f"Transmission: {self._costs[COST_GAS_TRANSMISSION]:.5f} EUR/kWh\n"
                f"Cotisation: {self._costs[COST_GAS_COTISATION]:.5f} EUR/kWh\n"
                f"Accise: {self._costs[COST_GAS_ACCISE]:.5f} EUR/kWh"
            ),
        }


class ElectricityPeakConsumptionSensor(BelgiumEnergyCostSensor):
    """Sensor for electricity peak consumption since contract start."""

    def __init__(self, hass: HomeAssistant, config: dict, import_config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._p1_sensor = import_config[CONF_P1_SENSORS][SENSOR_PEAK]
        self._baseline = import_config[CONF_BASELINE_READINGS][SENSOR_PEAK]
        self._attr_name = "Electricity Peak Consumption Since Contract Start"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_ELEC_PEAK_CONSUMPTION}"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:lightning-bolt"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [self._p1_sensor], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        current = self._get_state_value(self._p1_sensor)
        return round(current - self._baseline, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        current = self._get_state_value(self._p1_sensor)
        return {
            "current_reading": f"{current} kWh",
            "baseline_reading": f"{self._baseline} kWh",
        }


class ElectricityOffPeakConsumptionSensor(BelgiumEnergyCostSensor):
    """Sensor for electricity off-peak consumption since contract start."""

    def __init__(self, hass: HomeAssistant, config: dict, import_config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._p1_sensor = import_config[CONF_P1_SENSORS][SENSOR_OFFPEAK]
        self._baseline = import_config[CONF_BASELINE_READINGS][SENSOR_OFFPEAK]
        self._attr_name = "Electricity Off-Peak Consumption Since Contract Start"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_ELEC_OFFPEAK_CONSUMPTION}"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:lightning-bolt-outline"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [self._p1_sensor], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        current = self._get_state_value(self._p1_sensor)
        return round(current - self._baseline, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        current = self._get_state_value(self._p1_sensor)
        return {
            "current_reading": f"{current} kWh",
            "baseline_reading": f"{self._baseline} kWh",
        }


class ElectricitySingleConsumptionSensor(BelgiumEnergyCostSensor):
    """Sensor for electricity consumption since contract start (single tariff)."""

    def __init__(self, hass: HomeAssistant, config: dict, import_config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._p1_sensor = import_config[CONF_P1_SENSORS][SENSOR_TOTAL]
        self._baseline = import_config[CONF_BASELINE_READINGS][SENSOR_TOTAL]
        self._attr_name = "Electricity Consumption Since Contract Start"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_ELEC_SINGLE_CONSUMPTION}"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:lightning-bolt"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [self._p1_sensor], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        current = self._get_state_value(self._p1_sensor)
        return round(current - self._baseline, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        current = self._get_state_value(self._p1_sensor)
        return {
            "current_reading": f"{current} kWh",
            "baseline_reading": f"{self._baseline} kWh",
        }


class ElectricityExportTotalSensor(BelgiumEnergyCostSensor):
    """Sensor for total electricity export since contract start."""

    def __init__(self, hass: HomeAssistant, config: dict, export_config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        # Handle both single and bi-horaire export
        p1_sensors = export_config[CONF_P1_SENSORS]
        baselines = export_config[CONF_BASELINE_READINGS]
        
        if SENSOR_TOTAL in p1_sensors:
            self._p1_sensor = p1_sensors[SENSOR_TOTAL]
            self._baseline = baselines[SENSOR_TOTAL]
            self._is_single = True
        else:
            self._p1_sensor_peak = p1_sensors[SENSOR_PEAK]
            self._p1_sensor_offpeak = p1_sensors[SENSOR_OFFPEAK]
            self._baseline_peak = baselines[SENSOR_PEAK]
            self._baseline_offpeak = baselines[SENSOR_OFFPEAK]
            self._is_single = False
        
        self._attr_name = "Electricity Total Export Since Contract Start"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_ELEC_EXPORT_TOTAL}"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:solar-power"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        if self._is_single:
            sensors = [self._p1_sensor]
        else:
            sensors = [self._p1_sensor_peak, self._p1_sensor_offpeak]
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, sensors, sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        if self._is_single:
            current = self._get_state_value(self._p1_sensor)
            return round(current - self._baseline, 2)
        else:
            current_peak = self._get_state_value(self._p1_sensor_peak)
            current_offpeak = self._get_state_value(self._p1_sensor_offpeak)
            total_current = current_peak + current_offpeak
            total_baseline = self._baseline_peak + self._baseline_offpeak
            return round(total_current - total_baseline, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        if self._is_single:
            current = self._get_state_value(self._p1_sensor)
            return {
                "current_reading": f"{current} kWh",
                "baseline_reading": f"{self._baseline} kWh",
            }
        else:
            current_peak = self._get_state_value(self._p1_sensor_peak)
            current_offpeak = self._get_state_value(self._p1_sensor_offpeak)
            return {
                "current_peak": f"{current_peak} kWh",
                "current_offpeak": f"{current_offpeak} kWh",
                "baseline_peak": f"{self._baseline_peak} kWh",
                "baseline_offpeak": f"{self._baseline_offpeak} kWh",
            }


class ElectricityExportRevenueSensor(BelgiumEnergyCostSensor):
    """Sensor for electricity injection revenue since contract start."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._attr_name = "Electricity Injection Revenue Since Contract Start"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_ELEC_EXPORT_REVENUE}"
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:cash-plus"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        export_sensor = f"sensor.{SENSOR_ELEC_EXPORT_TOTAL}"
        injection_price_sensor = f"sensor.{SENSOR_TOTAL_ELEC_INJECTION}"
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [export_sensor, injection_price_sensor], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        export_kwh = self._get_state_value(f"sensor.{SENSOR_ELEC_EXPORT_TOTAL}")
        injection_price = self._get_state_value(f"sensor.{SENSOR_TOTAL_ELEC_INJECTION}")
        return round(export_kwh * injection_price, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        export_kwh = self._get_state_value(f"sensor.{SENSOR_ELEC_EXPORT_TOTAL}")
        injection_price = self._get_state_value(f"sensor.{SENSOR_TOTAL_ELEC_INJECTION}")
        return {
            "export_kwh": f"{export_kwh} kWh",
            "injection_price": f"{injection_price} EUR/kWh",
        }


class ElectricityTotalCostSensor(BelgiumEnergyCostSensor):
    """Sensor for total electricity cost since contract start."""

    def __init__(self, hass: HomeAssistant, config: dict, meter_type: str, costs: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._meter_type = meter_type
        self._costs = costs
        self._attr_name = "Electricity Total Cost Since Contract Start"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_ELEC_TOTAL_COST}"
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:lightning-bolt-circle"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        sensors_to_track = [f"sensor.{SENSOR_MONTHS_SINCE_START}"]
        
        if self._meter_type == METER_TYPE_BI_HORAIRE:
            sensors_to_track.extend([
                f"sensor.{SENSOR_ELEC_PEAK_CONSUMPTION}",
                f"sensor.{SENSOR_ELEC_OFFPEAK_CONSUMPTION}",
                f"sensor.{SENSOR_TOTAL_ELEC_PEAK}",
                f"sensor.{SENSOR_TOTAL_ELEC_OFFPEAK}",
            ])
        else:
            sensors_to_track.extend([
                f"sensor.{SENSOR_ELEC_SINGLE_CONSUMPTION}",
                f"sensor.{SENSOR_TOTAL_ELEC_SINGLE}",
            ])
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, sensors_to_track, sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        months = self._calculate_months_since_start()
        fixed_monthly = self._costs[COST_FIXED_MONTHLY]
        fixed_total = months * fixed_monthly
        
        if self._meter_type == METER_TYPE_BI_HORAIRE:
            peak_kwh = self._get_state_value(f"sensor.{SENSOR_ELEC_PEAK_CONSUMPTION}")
            offpeak_kwh = self._get_state_value(f"sensor.{SENSOR_ELEC_OFFPEAK_CONSUMPTION}")
            peak_cost = self._get_state_value(f"sensor.{SENSOR_TOTAL_ELEC_PEAK}")
            offpeak_cost = self._get_state_value(f"sensor.{SENSOR_TOTAL_ELEC_OFFPEAK}")
            energy_cost = (peak_kwh * peak_cost) + (offpeak_kwh * offpeak_cost)
        else:
            consumption_kwh = self._get_state_value(f"sensor.{SENSOR_ELEC_SINGLE_CONSUMPTION}")
            cost_per_kwh = self._get_state_value(f"sensor.{SENSOR_TOTAL_ELEC_SINGLE}")
            energy_cost = consumption_kwh * cost_per_kwh
        
        return round(energy_cost + fixed_total, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        months = self._calculate_months_since_start()
        fixed_monthly = self._costs[COST_FIXED_MONTHLY]
        fixed_total = months * fixed_monthly
        
        attrs = {
            "fixed_costs": f"{fixed_total:.2f} EUR ({months} months)",
            "period": f"{self._contract_start.strftime('%B %Y')} - {dt_util.now().strftime('%B %Y')}",
        }
        
        if self._meter_type == METER_TYPE_BI_HORAIRE:
            peak_kwh = self._get_state_value(f"sensor.{SENSOR_ELEC_PEAK_CONSUMPTION}")
            offpeak_kwh = self._get_state_value(f"sensor.{SENSOR_ELEC_OFFPEAK_CONSUMPTION}")
            peak_cost_rate = self._get_state_value(f"sensor.{SENSOR_TOTAL_ELEC_PEAK}")
            offpeak_cost_rate = self._get_state_value(f"sensor.{SENSOR_TOTAL_ELEC_OFFPEAK}")
            
            attrs.update({
                "peak_consumption": f"{peak_kwh} kWh",
                "offpeak_consumption": f"{offpeak_kwh} kWh",
                "peak_cost": f"{peak_kwh * peak_cost_rate:.2f} EUR",
                "offpeak_cost": f"{offpeak_kwh * offpeak_cost_rate:.2f} EUR",
            })
        else:
            consumption_kwh = self._get_state_value(f"sensor.{SENSOR_ELEC_SINGLE_CONSUMPTION}")
            attrs.update({
                "consumption": f"{consumption_kwh} kWh",
            })
        
        return attrs


class ElectricityNetCostSensor(BelgiumEnergyCostSensor):
    """Sensor for net electricity cost (consumption - solar revenue)."""

    def __init__(self, hass: HomeAssistant, config: dict, meter_type: str) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._meter_type = meter_type
        self._attr_name = "Electricity Net Cost Since Contract Start"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_ELEC_NET_COST}"
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:cash-minus"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [
                f"sensor.{SENSOR_ELEC_TOTAL_COST}",
                f"sensor.{SENSOR_ELEC_EXPORT_REVENUE}",
            ], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        total_cost = self._get_state_value(f"sensor.{SENSOR_ELEC_TOTAL_COST}")
        revenue = self._get_state_value(f"sensor.{SENSOR_ELEC_EXPORT_REVENUE}")
        return round(total_cost - revenue, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        total_cost = self._get_state_value(f"sensor.{SENSOR_ELEC_TOTAL_COST}")
        revenue = self._get_state_value(f"sensor.{SENSOR_ELEC_EXPORT_REVENUE}")
        return {
            "consumption_cost": f"{total_cost:.2f} EUR",
            "injection_revenue": f"{revenue:.2f} EUR",
        }


class ElectricityAnnualCostSensor(BelgiumEnergyCostSensor):
    """Sensor for estimated annual electricity cost."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._attr_name = "Electricity Estimated Annual Cost"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_ELEC_ANNUAL_COST}"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/year"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:calendar-lightning"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [
                f"sensor.{SENSOR_ELEC_TOTAL_COST}",
                f"sensor.{SENSOR_MONTHS_SINCE_START}",
            ], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        total_cost = self._get_state_value(f"sensor.{SENSOR_ELEC_TOTAL_COST}")
        months = self._calculate_months_since_start()
        
        if months > 0:
            monthly_avg = total_cost / months
            return round(monthly_avg * 12, 0)
        return 0
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        total_cost = self._get_state_value(f"sensor.{SENSOR_ELEC_TOTAL_COST}")
        months = self._calculate_months_since_start()
        
        if months > 0:
            monthly_avg = total_cost / months
            return {
                "monthly_average": f"{monthly_avg:.2f} EUR/month",
            }
        return {}


class ElectricityAnnualRevenueSensor(BelgiumEnergyCostSensor):
    """Sensor for estimated annual solar injection revenue."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._attr_name = "Electricity Estimated Annual Injection Revenue"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_ELEC_ANNUAL_REVENUE}"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/year"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:solar-power-variant"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [
                f"sensor.{SENSOR_ELEC_EXPORT_REVENUE}",
                f"sensor.{SENSOR_MONTHS_SINCE_START}",
            ], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        total_revenue = self._get_state_value(f"sensor.{SENSOR_ELEC_EXPORT_REVENUE}")
        months = self._calculate_months_since_start()
        
        if months > 0:
            monthly_avg = total_revenue / months
            return round(monthly_avg * 12, 0)
        return 0
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        total_revenue = self._get_state_value(f"sensor.{SENSOR_ELEC_EXPORT_REVENUE}")
        months = self._calculate_months_since_start()
        
        if months > 0:
            monthly_avg = total_revenue / months
            return {
                "monthly_average": f"{monthly_avg:.2f} EUR/month",
            }
        return {}


class GasTotalCostSensor(BelgiumEnergyCostSensor):
    """Sensor for total gas cost since contract start."""

    def __init__(self, hass: HomeAssistant, config: dict, costs: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._costs = costs
        self._conversion = config[CONF_GAS][CONF_CONVERSION_FACTOR]
        self._baseline_m3 = config[CONF_GAS][CONF_BASELINE_READING_M3]
        self._attr_name = "Gas Total Cost Since Contract Start"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_GAS_TOTAL_COST}"
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:fire-circle"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [
                f"sensor.{SENSOR_TOTAL_GAS}",
                f"sensor.{SENSOR_MONTHS_SINCE_START}",
                GAS_METER_ENTITY_ID,  # Manual gas reading
            ], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        # Get current gas meter reading in m³
        current_m3 = self._get_state_value(GAS_METER_ENTITY_ID)
        consumption_m3 = current_m3 - self._baseline_m3
        consumption_kwh = consumption_m3 * self._conversion
        
        # Calculate energy cost
        cost_per_kwh = self._get_state_value(f"sensor.{SENSOR_TOTAL_GAS}")
        energy_cost = consumption_kwh * cost_per_kwh
        
        # Calculate fixed costs
        months = self._calculate_months_since_start()
        fixed_monthly = self._costs[COST_GAS_FIXED_MONTHLY]
        fixed_total = months * fixed_monthly
        
        return round(energy_cost + fixed_total, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        current_m3 = self._get_state_value(GAS_METER_ENTITY_ID)
        consumption_m3 = current_m3 - self._baseline_m3
        consumption_kwh = consumption_m3 * self._conversion
        cost_per_kwh = self._get_state_value(f"sensor.{SENSOR_TOTAL_GAS}")
        energy_cost = consumption_kwh * cost_per_kwh
        
        months = self._calculate_months_since_start()
        fixed_monthly = self._costs[COST_GAS_FIXED_MONTHLY]
        fixed_total = months * fixed_monthly
        
        return {
            "consumption_kwh": f"{consumption_kwh:.2f} kWh",
            "consumption_m3": f"{consumption_m3:.3f} m³",
            "energy_costs": f"{energy_cost:.2f} EUR",
            "fixed_costs": f"{fixed_total:.2f} EUR ({months} months)",
            "cost_per_kwh": f"{cost_per_kwh} EUR/kWh",
            "period": f"{self._contract_start.strftime('%B %Y')} - {dt_util.now().strftime('%B %Y')}",
        }


class GasAnnualCostSensor(BelgiumEnergyCostSensor):
    """Sensor for estimated annual gas cost."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._conversion = config[CONF_GAS][CONF_CONVERSION_FACTOR]
        self._baseline_m3 = config[CONF_GAS][CONF_BASELINE_READING_M3]
        self._costs = config[CONF_GAS][CONF_COSTS]
        self._attr_name = "Gas Estimated Annual Cost"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_GAS_ANNUAL_COST}"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/year"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:calendar-fire"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [
                f"sensor.{SENSOR_TOTAL_GAS}",
                f"sensor.{SENSOR_MONTHS_SINCE_START}",
                GAS_METER_ENTITY_ID,
            ], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        # Calculate average monthly consumption
        current_m3 = self._get_state_value(GAS_METER_ENTITY_ID)
        consumption_m3 = current_m3 - self._baseline_m3
        consumption_kwh = consumption_m3 * self._conversion
        months = self._calculate_months_since_start()
        
        if months > 0:
            avg_monthly_kwh = consumption_kwh / months
            cost_per_kwh = self._get_state_value(f"sensor.{SENSOR_TOTAL_GAS}")
            monthly_energy_cost = avg_monthly_kwh * cost_per_kwh
            fixed_monthly = self._costs[COST_GAS_FIXED_MONTHLY]
            monthly_total = monthly_energy_cost + fixed_monthly
            return round(monthly_total * 12, 0)
        return 0
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        current_m3 = self._get_state_value(GAS_METER_ENTITY_ID)
        consumption_m3 = current_m3 - self._baseline_m3
        consumption_kwh = consumption_m3 * self._conversion
        months = self._calculate_months_since_start()
        
        if months > 0:
            avg_monthly_kwh = consumption_kwh / months
            cost_per_kwh = self._get_state_value(f"sensor.{SENSOR_TOTAL_GAS}")
            monthly_energy_cost = avg_monthly_kwh * cost_per_kwh
            fixed_monthly = self._costs[COST_GAS_FIXED_MONTHLY]
            monthly_total = monthly_energy_cost + fixed_monthly
            
            return {
                "monthly_average": f"{monthly_total:.2f} EUR/month",
                "energy_cost_annual": f"{monthly_energy_cost * 12:.2f} EUR/year",
                "fixed_cost_annual": f"{fixed_monthly * 12:.2f} EUR/year",
                "avg_monthly_consumption": f"{avg_monthly_kwh:.0f} kWh/month",
            }
        return {}


class GasConsumptionSensor(BelgiumEnergyCostSensor):
    """Sensor for gas consumption since contract start (m³)."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._baseline_m3 = config[CONF_GAS][CONF_BASELINE_READING_M3]
        self._attr_name = "Gas Consumption Since Contract Start"
        self._attr_unique_id = f"{DOMAIN}_gas_consumption_m3"
        self._attr_native_unit_of_measurement = "m³"
        self._attr_device_class = SensorDeviceClass.GAS
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:meter-gas"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [GAS_METER_ENTITY_ID], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        current_m3 = self._get_state_value(GAS_METER_ENTITY_ID)
        return round(current_m3 - self._baseline_m3, 3)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        current_m3 = self._get_state_value(GAS_METER_ENTITY_ID)
        return {
            "current_reading": f"{current_m3:.3f} m³",
            "baseline_reading": f"{self._baseline_m3:.3f} m³",
        }


class GasConsumptionKwhSensor(BelgiumEnergyCostSensor):
    """Sensor for gas consumption since contract start (kWh)."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._baseline_m3 = config[CONF_GAS][CONF_BASELINE_READING_M3]
        self._conversion = config[CONF_GAS][CONF_CONVERSION_FACTOR]
        self._attr_name = "Gas Consumption Since Contract Start (kWh)"
        self._attr_unique_id = f"{DOMAIN}_gas_consumption_kwh"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:fire"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [GAS_METER_ENTITY_ID], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        current_m3 = self._get_state_value(GAS_METER_ENTITY_ID)
        consumption_m3 = current_m3 - self._baseline_m3
        return round(consumption_m3 * self._conversion, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        current_m3 = self._get_state_value(GAS_METER_ENTITY_ID)
        consumption_m3 = current_m3 - self._baseline_m3
        return {
            "consumption_m3": f"{consumption_m3:.3f} m³",
            "conversion_factor": f"{self._conversion} kWh/m³",
        }


class ElectricityAverageMonthlyConsumptionSensor(BelgiumEnergyCostSensor):
    """Sensor for average monthly electricity consumption."""

    def __init__(self, hass: HomeAssistant, config: dict, meter_type: str) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._meter_type = meter_type
        self._attr_name = "Electricity Average Monthly Consumption"
        self._attr_unique_id = f"{DOMAIN}_electricity_avg_monthly_consumption"
        self._attr_native_unit_of_measurement = f"{UnitOfEnergy.KILO_WATT_HOUR}/month"
        self._attr_icon = "mdi:calendar-month"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        sensors_to_track = [f"sensor.{SENSOR_MONTHS_SINCE_START}"]
        if self._meter_type == METER_TYPE_BI_HORAIRE:
            sensors_to_track.extend([
                f"sensor.{SENSOR_ELEC_PEAK_CONSUMPTION}",
                f"sensor.{SENSOR_ELEC_OFFPEAK_CONSUMPTION}",
            ])
        else:
            sensors_to_track.append(f"sensor.{SENSOR_ELEC_SINGLE_CONSUMPTION}")
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, sensors_to_track, sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0
        
        if self._meter_type == METER_TYPE_BI_HORAIRE:
            peak = self._get_state_value(f"sensor.{SENSOR_ELEC_PEAK_CONSUMPTION}")
            offpeak = self._get_state_value(f"sensor.{SENSOR_ELEC_OFFPEAK_CONSUMPTION}")
            total_consumption = peak + offpeak
        else:
            total_consumption = self._get_state_value(f"sensor.{SENSOR_ELEC_SINGLE_CONSUMPTION}")
        
        return round(total_consumption / months, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        months = self._calculate_months_since_start()
        if self._meter_type == METER_TYPE_BI_HORAIRE:
            peak = self._get_state_value(f"sensor.{SENSOR_ELEC_PEAK_CONSUMPTION}")
            offpeak = self._get_state_value(f"sensor.{SENSOR_ELEC_OFFPEAK_CONSUMPTION}")
            return {
                "peak_avg_monthly": f"{peak / months if months > 0 else 0:.2f} kWh/month",
                "offpeak_avg_monthly": f"{offpeak / months if months > 0 else 0:.2f} kWh/month",
                "months_elapsed": months,
            }
        return {"months_elapsed": months}


class ElectricityAverageMonthlyCostSensor(BelgiumEnergyCostSensor):
    """Sensor for average monthly electricity cost."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._attr_name = "Electricity Average Monthly Cost"
        self._attr_unique_id = f"{DOMAIN}_electricity_avg_monthly_cost"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/month"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:calendar-cash"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [
                f"sensor.{SENSOR_ELEC_TOTAL_COST}",
                f"sensor.{SENSOR_MONTHS_SINCE_START}",
            ], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0
        
        total_cost = self._get_state_value(f"sensor.{SENSOR_ELEC_TOTAL_COST}")
        return round(total_cost / months, 2)


class GasAverageMonthlyConsumptionSensor(BelgiumEnergyCostSensor):
    """Sensor for average monthly gas consumption (kWh)."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._baseline_m3 = config[CONF_GAS][CONF_BASELINE_READING_M3]
        self._conversion = config[CONF_GAS][CONF_CONVERSION_FACTOR]
        self._attr_name = "Gas Average Monthly Consumption"
        self._attr_unique_id = f"{DOMAIN}_gas_avg_monthly_consumption"
        self._attr_native_unit_of_measurement = f"{UnitOfEnergy.KILO_WATT_HOUR}/month"
        self._attr_icon = "mdi:calendar-month"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [
                GAS_METER_ENTITY_ID,
                f"sensor.{SENSOR_MONTHS_SINCE_START}",
            ], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0
        
        current_m3 = self._get_state_value(GAS_METER_ENTITY_ID)
        consumption_m3 = current_m3 - self._baseline_m3
        consumption_kwh = consumption_m3 * self._conversion
        return round(consumption_kwh / months, 2)


class GasAverageMonthlyCostSensor(BelgiumEnergyCostSensor):
    """Sensor for average monthly gas cost."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._attr_name = "Gas Average Monthly Cost"
        self._attr_unique_id = f"{DOMAIN}_gas_avg_monthly_cost"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/month"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:calendar-cash"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, [
                f"sensor.{SENSOR_GAS_TOTAL_COST}",
                f"sensor.{SENSOR_MONTHS_SINCE_START}",
            ], sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0
        
        total_cost = self._get_state_value(f"sensor.{SENSOR_GAS_TOTAL_COST}")
        return round(total_cost / months, 2)


class TotalAverageMonthlyEnergyCostSensor(BelgiumEnergyCostSensor):
    """Sensor for average monthly total energy cost."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._has_gas = config.get(CONF_GAS, {}).get(CONF_ENABLED, False)
        self._attr_name = "Total Average Monthly Energy Cost"
        self._attr_unique_id = f"{DOMAIN}_total_avg_monthly_cost"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/month"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:calendar-fire"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        sensors_to_track = [
            f"sensor.{SENSOR_TOTAL_ENERGY_COST}",
            f"sensor.{SENSOR_MONTHS_SINCE_START}",
        ]
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, sensors_to_track, sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        months = self._calculate_months_since_start()
        if months <= 0:
            return 0
        
        total_cost = self._get_state_value(f"sensor.{SENSOR_TOTAL_ENERGY_COST}")
        return round(total_cost / months, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        months = self._calculate_months_since_start()
        elec_monthly = self._get_state_value(f"sensor.{DOMAIN}_electricity_avg_monthly_cost")
        
        attrs = {
            "electricity_monthly": f"{elec_monthly:.2f} EUR/month",
            "months_elapsed": months,
        }
        
        if self._has_gas:
            gas_monthly = self._get_state_value(f"sensor.{DOMAIN}_gas_avg_monthly_cost")
            attrs["gas_monthly"] = f"{gas_monthly:.2f} EUR/month"
        
        return attrs


class TotalEnergyCostSensor(BelgiumEnergyCostSensor):
    """Sensor for total combined energy cost since contract start."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._has_gas = config.get(CONF_GAS, {}).get(CONF_ENABLED, False)
        self._attr_name = "Total Energy Cost Since Contract Start"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_TOTAL_ENERGY_COST}"
        self._attr_native_unit_of_measurement = CURRENCY_EURO
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:cash-multiple"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        sensors_to_track = [f"sensor.{SENSOR_ELEC_TOTAL_COST}"]
        if self._has_gas:
            sensors_to_track.append(f"sensor.{SENSOR_GAS_TOTAL_COST}")
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, sensors_to_track, sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        elec_cost = self._get_state_value(f"sensor.{SENSOR_ELEC_TOTAL_COST}")
        gas_cost = 0
        
        if self._has_gas:
            gas_cost = self._get_state_value(f"sensor.{SENSOR_GAS_TOTAL_COST}")
        
        return round(elec_cost + gas_cost, 2)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        elec_cost = self._get_state_value(f"sensor.{SENSOR_ELEC_TOTAL_COST}")
        months = self._calculate_months_since_start()
        
        attrs = {
            "electricity_cost": f"{elec_cost} EUR",
            "period": f"{self._contract_start.strftime('%B %Y')} - {dt_util.now().strftime('%B %Y')} ({months} months)",
        }
        
        if self._has_gas:
            gas_cost = self._get_state_value(f"sensor.{SENSOR_GAS_TOTAL_COST}")
            attrs["gas_cost"] = f"{gas_cost} EUR"
        
        return attrs


class TotalAnnualEnergyCostSensor(BelgiumEnergyCostSensor):
    """Sensor for total estimated annual energy cost."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize the sensor."""
        super().__init__(hass, config)
        self._has_gas = config.get(CONF_GAS, {}).get(CONF_ENABLED, False)
        self._attr_name = "Total Estimated Annual Energy Cost"
        self._attr_unique_id = f"{DOMAIN}_{SENSOR_TOTAL_ANNUAL_COST}"
        self._attr_native_unit_of_measurement = f"{CURRENCY_EURO}/year"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:cash-clock"
        self._unsubscribe = None
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        @callback
        def sensor_state_listener(event):
            """Handle state changes."""
            self.async_schedule_update_ha_state(True)
        
        sensors_to_track = [f"sensor.{SENSOR_ELEC_ANNUAL_COST}"]
        if self._has_gas:
            sensors_to_track.append(f"sensor.{SENSOR_GAS_ANNUAL_COST}")
        
        self._unsubscribe = async_track_state_change_event(
            self.hass, sensors_to_track, sensor_state_listener
        )
    
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks."""
        if self._unsubscribe:
            self._unsubscribe()
    
    @property
    def native_value(self) -> float | None:
        """Return the state."""
        elec_annual = self._get_state_value(f"sensor.{SENSOR_ELEC_ANNUAL_COST}")
        gas_annual = 0
        
        if self._has_gas:
            gas_annual = self._get_state_value(f"sensor.{SENSOR_GAS_ANNUAL_COST}")
        
        return round(elec_annual + gas_annual, 0)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        elec_annual = self._get_state_value(f"sensor.{SENSOR_ELEC_ANNUAL_COST}")
        total = self.native_value or 0
        
        attrs = {
            "electricity_annual": f"{elec_annual} EUR/year",
            "monthly_average": f"{total / 12:.2f} EUR/month",
        }
        
        if self._has_gas:
            gas_annual = self._get_state_value(f"sensor.{SENSOR_GAS_ANNUAL_COST}")
            attrs["gas_annual"] = f"{gas_annual} EUR/year"
        
        return attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Belgium Energy Costs sensors from config entry."""
    # Create mutable copy of config (entry.data is read-only)
    conf = dict(entry.data)
    
    # Parse contract start date
    from datetime import datetime
    if isinstance(conf[CONF_CONTRACT_START_DATE], str):
        conf[CONF_CONTRACT_START_DATE] = datetime.fromisoformat(conf[CONF_CONTRACT_START_DATE]).date()
    
    sensors = []
    
    # Contract duration sensor (always created)
    sensors.append(MonthsSinceContractStartSensor(hass, conf))
    
    # Electricity sensors
    meter_type = conf[CONF_ELECTRICITY][CONF_METER_TYPE]
    elec_costs = conf[CONF_ELECTRICITY][CONF_COSTS]
    elec_import = conf[CONF_ELECTRICITY][CONF_IMPORT]
    elec_export = conf[CONF_ELECTRICITY].get(CONF_EXPORT, {})
    
    if meter_type == METER_TYPE_BI_HORAIRE:
        # Bi-horaire cost sensors
        sensors.append(TotalElectricityCostPeakSensor(hass, conf, elec_costs))
        sensors.append(TotalElectricityCostOffPeakSensor(hass, conf, elec_costs))
        sensors.append(ElectricityPeakOffPeakSavingsSensor(hass, conf))
        
        # Bi-horaire consumption sensors
        sensors.append(ElectricityPeakConsumptionSensor(hass, conf, elec_import))
        sensors.append(ElectricityOffPeakConsumptionSensor(hass, conf, elec_import))
    else:
        # Single tariff sensors
        sensors.append(TotalElectricityCostSingleSensor(hass, conf, elec_costs))
        sensors.append(ElectricitySingleConsumptionSensor(hass, conf, elec_import))
    
    # Solar export sensors (if enabled)
    if elec_export.get(CONF_ENABLED, False):
        sensors.append(TotalElectricityInjectionPriceSensor(hass, conf))
        sensors.append(ElectricityExportTotalSensor(hass, conf, elec_export))
        sensors.append(ElectricityExportRevenueSensor(hass, conf))
        sensors.append(ElectricityNetCostSensor(hass, conf, meter_type))
        sensors.append(ElectricityAnnualRevenueSensor(hass, conf))
    
    # Electricity cost calculation sensors
    sensors.append(ElectricityTotalCostSensor(hass, conf, meter_type, elec_costs))
    sensors.append(ElectricityAnnualCostSensor(hass, conf))

    # Monthly average electricity sensors
    sensors.append(ElectricityAverageMonthlyConsumptionSensor(hass, conf, meter_type))
    sensors.append(ElectricityAverageMonthlyCostSensor(hass, conf))
    
    # Gas sensors (if enabled)
    if conf.get(CONF_GAS, {}).get(CONF_ENABLED, False):
        gas_costs = conf[CONF_GAS][CONF_COSTS]
        sensors.append(TotalGasCostSensor(hass, conf, gas_costs))
        sensors.append(GasTotalCostSensor(hass, conf, gas_costs))
        sensors.append(GasAnnualCostSensor(hass, conf))

        # Gas consumption sensors
        sensors.append(GasConsumptionSensor(hass, conf))
        sensors.append(GasConsumptionKwhSensor(hass, conf))

        # Monthly average gas sensors
        sensors.append(GasAverageMonthlyConsumptionSensor(hass, conf))
        sensors.append(GasAverageMonthlyCostSensor(hass, conf))
    
    # Combined total sensors
    sensors.append(TotalEnergyCostSensor(hass, conf))
    sensors.append(TotalAnnualEnergyCostSensor(hass, conf))

    # Monthly average total
    sensors.append(TotalAverageMonthlyEnergyCostSensor(hass, conf))
    
    async_add_entities(sensors, True)
