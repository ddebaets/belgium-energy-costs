"""Config flow for Belgium Energy Costs integration."""
from __future__ import annotations

import copy
import logging
from datetime import date, datetime
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    DateSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DOMAIN,
    CONF_CONTRACT_START_DATE,
    CONF_REGION,
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
    REGION_BRUSSELS,
    REGION_FLANDERS,
    REGION_WALLONIA,
    REGIONAL_DEFAULTS,
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

# Total number of setup steps — used for "Step X of Y" progress display.
_TOTAL_STEPS = 8


def _step_note(step: int, description: str) -> str:
    """Return a description prefixed with a step progress indicator."""
    return f"Step {step} of {_TOTAL_STEPS} — {description}"


class BelgiumEnergyCostsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Belgium Energy Costs."""

    VERSION = 2  # Must match CONFIG_ENTRY_VERSION in __init__.py

    def __init__(self):
        self.config_data: dict[str, Any] = {
            CONF_REGION: REGION_BRUSSELS,
        }

    # ------------------------------------------------------------------
    # Step 1 – Region
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Region selection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            region = user_input[CONF_REGION]
            self.config_data[CONF_REGION] = region
            if not REGIONAL_DEFAULTS[region]["supported"]:
                errors["base"] = "region_not_supported"
            else:
                return await self.async_step_contract_dates()

        region_options = [
            {
                "value": k,
                "label": (
                    f"{v['name']} ({v['grid_operator']}) "
                    f"{'✅' if v['supported'] else '⚠️ Coming Soon'}"
                ),
            }
            for k, v in REGIONAL_DEFAULTS.items()
        ]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_REGION, default=REGION_BRUSSELS): SelectSelector(
                    SelectSelectorConfig(options=region_options, mode=SelectSelectorMode.DROPDOWN)
                ),
            }),
            errors=errors,
            description_placeholders={
                "note": _step_note(1, "Choose your region in Belgium."),
            },
        )

    # ------------------------------------------------------------------
    # Step 2 – Contract start dates (electricity + gas together)
    # ------------------------------------------------------------------

    async def async_step_contract_dates(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Contract start dates for electricity and gas."""
        if user_input is not None:
            elec_date = user_input["elec_contract_start_date"]
            gas_date = user_input["gas_contract_start_date"]
            if isinstance(elec_date, str):
                elec_date = datetime.fromisoformat(elec_date).date()
            if isinstance(gas_date, str):
                gas_date = datetime.fromisoformat(gas_date).date()
            self.config_data["elec_contract_start_date"] = elec_date
            self.config_data["gas_contract_start_date"] = gas_date
            return await self.async_step_electricity_type()

        default_date = date(date.today().year, 1, 1)
        return self.async_show_form(
            step_id="contract_dates",
            data_schema=vol.Schema({
                vol.Required("elec_contract_start_date", default=default_date): DateSelector(
                    DateSelectorConfig()
                ),
                vol.Required("gas_contract_start_date", default=default_date): DateSelector(
                    DateSelectorConfig()
                ),
            }),
            description_placeholders={
                "note": _step_note(
                    2,
                    "⚡ Electricity: the date your current electricity contract started.\n"
                    "🔥 Gas: the date your current gas contract started.\n"
                    "Using the same supplier for both? The dates are likely identical.\n\n"
                    "⚠️ Cost calculations for past consumption use current prices as an approximation.",
                ),
            },
        )

    # ------------------------------------------------------------------
    # Step 3 – Electricity meter type
    # ------------------------------------------------------------------

    async def async_step_electricity_type(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 3: Electricity meter type."""
        if user_input is not None:
            self.config_data[CONF_METER_TYPE] = user_input[CONF_METER_TYPE]
            return await self.async_step_electricity_sensors()

        return self.async_show_form(
            step_id="electricity_type",
            data_schema=vol.Schema({
                vol.Required(CONF_METER_TYPE, default=METER_TYPE_BI_HORAIRE): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": METER_TYPE_BI_HORAIRE, "label": "Bi-horaire (Day/Night tariff)"},
                            {"value": METER_TYPE_SINGLE, "label": "Single tariff"},
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
            description_placeholders={
                "note": _step_note(
                    3,
                    "Bi-horaire meters track peak (weekdays 7h–22h) and off-peak "
                    "(nights + weekends) consumption separately.",
                ),
            },
        )

    # ------------------------------------------------------------------
    # Step 4 – Electricity P1 sensors
    # ------------------------------------------------------------------

    async def async_step_electricity_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 4: P1 meter sensor selection."""
        errors: dict[str, str] = {}
        meter_type = self.config_data[CONF_METER_TYPE]

        if user_input is not None:
            if meter_type == METER_TYPE_BI_HORAIRE:
                for field in ("peak_sensor", "offpeak_sensor"):
                    if not self.hass.states.get(user_input[field]):
                        errors[field] = "entity_not_found"
                if not errors:
                    self.config_data["elec_peak_sensor"] = user_input["peak_sensor"]
                    self.config_data["elec_offpeak_sensor"] = user_input["offpeak_sensor"]
                    self.config_data["elec_peak_baseline"] = user_input["peak_baseline"]
                    self.config_data["elec_offpeak_baseline"] = user_input["offpeak_baseline"]
                    return await self.async_step_solar_export()
            else:
                if not self.hass.states.get(user_input["total_sensor"]):
                    errors["total_sensor"] = "entity_not_found"
                if not errors:
                    self.config_data["elec_total_sensor"] = user_input["total_sensor"]
                    self.config_data["elec_total_baseline"] = user_input["total_baseline"]
                    return await self.async_step_solar_export()

        if meter_type == METER_TYPE_BI_HORAIRE:
            schema = vol.Schema({
                vol.Required("peak_sensor"): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required("peak_baseline", default=0): NumberSelector(
                    NumberSelectorConfig(min=0, max=999999, mode=NumberSelectorMode.BOX, unit_of_measurement="kWh")
                ),
                vol.Required("offpeak_sensor"): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required("offpeak_baseline", default=0): NumberSelector(
                    NumberSelectorConfig(min=0, max=999999, mode=NumberSelectorMode.BOX, unit_of_measurement="kWh")
                ),
            })
            note = "Select your peak and off-peak P1 sensors, and enter the meter readings at your contract start date."
        else:
            schema = vol.Schema({
                vol.Required("total_sensor"): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required("total_baseline", default=0): NumberSelector(
                    NumberSelectorConfig(min=0, max=999999, mode=NumberSelectorMode.BOX, unit_of_measurement="kWh")
                ),
            })
            note = "Select your P1 consumption sensor and enter the meter reading at your contract start date."

        return self.async_show_form(
            step_id="electricity_sensors",
            data_schema=schema,
            errors=errors,
            description_placeholders={"note": _step_note(4, note)},
        )

    # ------------------------------------------------------------------
    # Step 5 – Solar export
    # ------------------------------------------------------------------

    async def async_step_solar_export(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 5: Solar panel / export configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            has_solar = user_input.get("has_solar", False)
            self.config_data["has_solar"] = has_solar
            if has_solar:
                export_sensor = user_input.get("export_sensor")
                if not export_sensor:
                    errors["export_sensor"] = "required"
                elif not self.hass.states.get(export_sensor):
                    errors["export_sensor"] = "entity_not_found"
                if not errors:
                    self.config_data["export_sensor"] = export_sensor
                    self.config_data["export_baseline"] = user_input.get("export_baseline", 0)
                    return await self.async_step_electricity_costs()
            else:
                return await self.async_step_electricity_costs()

        return self.async_show_form(
            step_id="solar_export",
            data_schema=vol.Schema({
                vol.Required("has_solar", default=False): BooleanSelector(),
                vol.Optional("export_sensor"): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Optional("export_baseline", default=0): NumberSelector(
                    NumberSelectorConfig(min=0, max=999999, mode=NumberSelectorMode.BOX, unit_of_measurement="kWh")
                ),
            }),
            errors=errors,
            description_placeholders={
                "note": _step_note(
                    5,
                    "Do you have solar panels that inject electricity back to the grid?",
                ),
            },
        )

    # ------------------------------------------------------------------
    # Step 6 – Electricity costs
    # ------------------------------------------------------------------

    async def async_step_electricity_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 6: Electricity fixed cost components."""
        if user_input is not None:
            self.config_data["elec_costs"] = user_input
            return await self.async_step_gas_config()

        meter_type = self.config_data[CONF_METER_TYPE]
        if meter_type == METER_TYPE_BI_HORAIRE:
            schema = vol.Schema({
                vol.Required(COST_GREEN_CERT, default=0.0275): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_DIST_PEAK, default=0.0941): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_DIST_OFFPEAK, default=0.0706): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_TRANSMISSION, default=0.0225): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_COTISATION, default=0.00204): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_ACCISE, default=0.05033): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_FIXED_MONTHLY, default=14.05): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
            })
        else:
            schema = vol.Schema({
                vol.Required(COST_GREEN_CERT, default=0.0275): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_DIST_SINGLE, default=0.0823): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_TRANSMISSION, default=0.0225): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_COTISATION, default=0.00204): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_ACCISE, default=0.05033): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_FIXED_MONTHLY, default=14.05): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
            })

        return self.async_show_form(
            step_id="electricity_costs",
            data_schema=schema,
            description_placeholders={
                "note": _step_note(
                    6,
                    "Enter fixed electricity costs from your ENGIE contract (pages 21–22). "
                    "All values in EUR/kWh except fixed monthly (EUR/month). "
                    "These can be updated later via the integration options.",
                ),
            },
        )

    # ------------------------------------------------------------------
    # Step 7 – Gas configuration
    # ------------------------------------------------------------------

    async def async_step_gas_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 7: Gas meter readings and conversion factor."""
        errors: dict[str, str] = {}
        region = self.config_data[CONF_REGION]
        default_conversion = REGIONAL_DEFAULTS[region]["gas_conversion"]
        grid_operator = REGIONAL_DEFAULTS[region]["grid_operator"]

        if user_input is not None:
            has_gas = user_input.get("has_gas", False)
            self.config_data["has_gas"] = has_gas

            if not has_gas:
                return await self._async_create_entry()

            gas_baseline = user_input["gas_baseline"]
            gas_current = user_input["gas_current"]

            if gas_current < gas_baseline:
                errors["gas_current"] = "gas_current_below_baseline"
            else:
                self.config_data["gas_baseline_m3"] = gas_baseline
                self.config_data["gas_current_m3"] = gas_current
                self.config_data["gas_conversion"] = user_input.get("gas_conversion", default_conversion)
                return await self.async_step_gas_costs()

        return self.async_show_form(
            step_id="gas_config",
            data_schema=vol.Schema({
                vol.Required("has_gas", default=True): BooleanSelector(),
                vol.Required("gas_baseline", default=0): NumberSelector(
                    NumberSelectorConfig(min=0, max=999999, mode=NumberSelectorMode.BOX, unit_of_measurement="m³")
                ),
                vol.Required("gas_current"): NumberSelector(
                    NumberSelectorConfig(min=0, max=999999, mode=NumberSelectorMode.BOX, unit_of_measurement="m³")
                ),
                vol.Required("gas_conversion", default=default_conversion): NumberSelector(
                    NumberSelectorConfig(mode=NumberSelectorMode.BOX, unit_of_measurement="kWh/m³")
                ),
            }),
            errors=errors,
            description_placeholders={
                "grid_operator": grid_operator,
                "default_conversion": str(default_conversion),
                "note": _step_note(
                    7,
                    f"📋 Baseline: your gas meter reading on your contract start date.\n"
                    f"📍 Current reading: what your physical meter shows TODAY.\n"
                    f"Both values are required — without today's reading no consumption can be calculated.\n"
                    f"Default conversion factor for {grid_operator}: {default_conversion} kWh/m³",
                ),
            },
        )

    # ------------------------------------------------------------------
    # Step 9 – Gas costs
    # ------------------------------------------------------------------

    async def async_step_gas_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 9: Gas fixed cost components."""
        if user_input is not None:
            self.config_data["gas_costs"] = user_input
            return await self._async_create_entry()

        return self.async_show_form(
            step_id="gas_costs",
            data_schema=vol.Schema({
                vol.Required(COST_GAS_DISTRIBUTION, default=0.01949): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_GAS_TRANSMISSION, default=0.00165): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_GAS_COTISATION, default=0.00106): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_GAS_ACCISE, default=0.00872): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_GAS_FIXED_MONTHLY, default=7.57): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
            }),
            description_placeholders={
                "note": _step_note(
                    8,
                    "Enter fixed gas costs from your ENGIE contract (pages 25–26). "
                    "All values in EUR/kWh except fixed monthly (EUR/month). "
                    "These can be updated later via the integration options.",
                ),
            },
        )

    # ------------------------------------------------------------------
    # Final assembly
    # ------------------------------------------------------------------

    async def _async_create_entry(self) -> FlowResult:
        """Assemble all collected data into a config entry."""
        meter_type = self.config_data[CONF_METER_TYPE]
        region = self.config_data[CONF_REGION]

        # Electricity import
        if meter_type == METER_TYPE_BI_HORAIRE:
            elec_import = {
                CONF_P1_SENSORS: {
                    SENSOR_PEAK: self.config_data["elec_peak_sensor"],
                    SENSOR_OFFPEAK: self.config_data["elec_offpeak_sensor"],
                },
                CONF_BASELINE_READINGS: {
                    SENSOR_PEAK: self.config_data["elec_peak_baseline"],
                    SENSOR_OFFPEAK: self.config_data["elec_offpeak_baseline"],
                },
            }
        else:
            elec_import = {
                CONF_P1_SENSORS: {SENSOR_TOTAL: self.config_data["elec_total_sensor"]},
                CONF_BASELINE_READINGS: {SENSOR_TOTAL: self.config_data["elec_total_baseline"]},
            }

        # Electricity export
        elec_export: dict[str, Any] = {CONF_ENABLED: self.config_data.get("has_solar", False)}
        if self.config_data.get("has_solar"):
            elec_export[CONF_P1_SENSORS] = {SENSOR_TOTAL: self.config_data["export_sensor"]}
            elec_export[CONF_BASELINE_READINGS] = {SENSOR_TOTAL: self.config_data["export_baseline"]}

        electricity = {
            CONF_CONTRACT_START_DATE: self.config_data["elec_contract_start_date"].isoformat(),
            CONF_METER_TYPE: meter_type,
            CONF_IMPORT: elec_import,
            CONF_EXPORT: elec_export,
            CONF_COSTS: self.config_data["elec_costs"],
        }

        # Gas
        gas: dict[str, Any] = {CONF_ENABLED: self.config_data.get("has_gas", False)}
        if self.config_data.get("has_gas"):
            gas[CONF_CONTRACT_START_DATE] = self.config_data["gas_contract_start_date"].isoformat()
            gas[CONF_BASELINE_READING_M3] = self.config_data["gas_baseline_m3"]
            gas["current_reading_m3"] = self.config_data["gas_current_m3"]
            gas[CONF_CONVERSION_FACTOR] = self.config_data["gas_conversion"]
            gas[CONF_COSTS] = self.config_data["gas_costs"]

        config = {
            CONF_REGION: region,
            CONF_ELECTRICITY: electricity,
            CONF_GAS: gas,
        }

        region_name = REGIONAL_DEFAULTS[region]["name"]
        return self.async_create_entry(
            title=f"Belgium Energy Costs ({region_name})",
            data=config,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return BelgiumEnergyCostsOptionsFlow()


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------

class BelgiumEnergyCostsOptionsFlow(config_entries.OptionsFlow):
    """Update costs and gas meter reading without reinstalling."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["electricity_costs", "gas_costs", "gas_reading"],
        )

    async def async_step_electricity_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Update electricity cost components."""
        if user_input is not None:
            new_data = copy.deepcopy(dict(self.config_entry.data))
            new_data[CONF_ELECTRICITY][CONF_COSTS] = user_input
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        current = self.config_entry.data[CONF_ELECTRICITY][CONF_COSTS]
        meter_type = self.config_entry.data[CONF_ELECTRICITY][CONF_METER_TYPE]

        if meter_type == METER_TYPE_BI_HORAIRE:
            schema = vol.Schema({
                vol.Required(COST_GREEN_CERT, default=current.get(COST_GREEN_CERT, 0.0275)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_DIST_PEAK, default=current.get(COST_DIST_PEAK, 0.0941)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_DIST_OFFPEAK, default=current.get(COST_DIST_OFFPEAK, 0.0706)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_TRANSMISSION, default=current.get(COST_TRANSMISSION, 0.0225)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_COTISATION, default=current.get(COST_COTISATION, 0.00204)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_ACCISE, default=current.get(COST_ACCISE, 0.05033)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_FIXED_MONTHLY, default=current.get(COST_FIXED_MONTHLY, 14.05)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
            })
        else:
            schema = vol.Schema({
                vol.Required(COST_GREEN_CERT, default=current.get(COST_GREEN_CERT, 0.0275)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_DIST_SINGLE, default=current.get(COST_DIST_SINGLE, 0.0823)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_TRANSMISSION, default=current.get(COST_TRANSMISSION, 0.0225)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_COTISATION, default=current.get(COST_COTISATION, 0.00204)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_ACCISE, default=current.get(COST_ACCISE, 0.05033)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_FIXED_MONTHLY, default=current.get(COST_FIXED_MONTHLY, 14.05)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
            })

        return self.async_show_form(
            step_id="electricity_costs",
            data_schema=schema,
            description_placeholders={"note": "Update values from your new ENGIE contract (pages 21–22)."},
        )

    async def async_step_gas_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Update gas cost components."""
        if not self.config_entry.data[CONF_GAS][CONF_ENABLED]:
            return self.async_abort(reason="gas_not_enabled")

        if user_input is not None:
            new_data = copy.deepcopy(dict(self.config_entry.data))
            new_data[CONF_GAS][CONF_COSTS] = user_input
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data={})

        current = self.config_entry.data[CONF_GAS][CONF_COSTS]
        return self.async_show_form(
            step_id="gas_costs",
            data_schema=vol.Schema({
                vol.Required(COST_GAS_DISTRIBUTION, default=current.get(COST_GAS_DISTRIBUTION, 0.01949)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_GAS_TRANSMISSION, default=current.get(COST_GAS_TRANSMISSION, 0.00165)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_GAS_COTISATION, default=current.get(COST_GAS_COTISATION, 0.00106)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_GAS_ACCISE, default=current.get(COST_GAS_ACCISE, 0.00872)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
                vol.Required(COST_GAS_FIXED_MONTHLY, default=current.get(COST_GAS_FIXED_MONTHLY, 7.57)): NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX)),
            }),
            description_placeholders={"note": "Update values from your new ENGIE contract (pages 25–26)."},
        )

    async def async_step_gas_reading(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Update the current gas meter reading."""
        if not self.config_entry.data[CONF_GAS][CONF_ENABLED]:
            return self.async_abort(reason="gas_not_enabled")

        if user_input is not None:
            await self.hass.services.async_call(
                DOMAIN, "update_gas_reading",
                {"reading": user_input["gas_reading"]},
            )
            return self.async_create_entry(title="", data={})

        from .const import get_gas_meter_entity_id
        current_reading = 0.0
        state = self.hass.states.get(get_gas_meter_entity_id(self.config_entry.entry_id))
        if state and state.state not in ("unknown", "unavailable"):
            try:
                current_reading = float(state.state)
            except (ValueError, TypeError):
                pass

        return self.async_show_form(
            step_id="gas_reading",
            data_schema=vol.Schema({
                vol.Required("gas_reading", default=current_reading): NumberSelector(
                    NumberSelectorConfig(min=0, max=999999, step=0.001,
                                        mode=NumberSelectorMode.BOX,
                                        unit_of_measurement="m³")
                ),
            }),
            description_placeholders={
                "note": "Enter your current gas meter reading (update monthly on the 1st).",
            },
        )
