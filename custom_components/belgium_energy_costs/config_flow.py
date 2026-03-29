"""Config flow for Belgium Energy Costs integration."""
from __future__ import annotations

import logging
from typing import Any
import voluptuous as vol
from datetime import date, datetime

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


class BelgiumEnergyCostsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Belgium Energy Costs."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self.config_data = {
            CONF_REGION: REGION_BRUSSELS,  # Default to Brussels
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - region selection."""
        if user_input is not None:
            region = user_input[CONF_REGION]
            self.config_data[CONF_REGION] = region
            
            # Check if region is supported
            if not REGIONAL_DEFAULTS[region]["supported"]:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._get_region_schema(),
                    errors={"base": "region_not_supported"},
                    description_placeholders={
                        "region_name": REGIONAL_DEFAULTS[region]["name"],
                        "grid_operator": REGIONAL_DEFAULTS[region]["grid_operator"],
                    },
                )
            
            return await self.async_step_contract_date()

        return self.async_show_form(
            step_id="user",
            data_schema=self._get_region_schema(),
            description_placeholders={
                "note": (
                    "Select your region in Belgium. This determines default values "
                    "for gas conversion factors and grid operator information."
                )
            },
        )
    
    def _get_region_schema(self) -> vol.Schema:
        """Get region selection schema."""
        region_options = []
        for region_key, region_data in REGIONAL_DEFAULTS.items():
            status = "✅ Supported" if region_data["supported"] else "⚠️ Coming Soon"
            label = f"{region_data['name']} ({region_data['grid_operator']}) {status}"
            region_options.append({"value": region_key, "label": label})
        
        return vol.Schema({
            vol.Required(CONF_REGION, default=REGION_BRUSSELS): SelectSelector(
                SelectSelectorConfig(
                    options=region_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        })

    async def async_step_contract_date(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle contract start date entry."""
        errors = {}

        if user_input is not None:
            # Validate contract start date
            contract_date = user_input[CONF_CONTRACT_START_DATE]
            
            # Convert string to date if needed
            if isinstance(contract_date, str):
                contract_date = datetime.fromisoformat(contract_date).date()
            
            # Check if ENGIE Belgium integration is installed
            engie_check = await self._check_engie_integration()
            if not engie_check["installed"]:
                errors["base"] = "engie_not_found"
            else:
                # Calculate months since contract start
                today = date.today()
                days_diff = (today - contract_date).days
                months_diff = days_diff / 30.44
                
                self.config_data[CONF_CONTRACT_START_DATE] = contract_date
                self.config_data["_months_ago"] = round(months_diff, 1)
                
                return await self.async_step_electricity_type()

        # Calculate default date (beginning of current year or 1 year ago)
        today = date.today()
        default_date = date(today.year, 1, 1)
        
        # Get region name (default to Brussels if not set - shouldn't happen)
        region = self.config_data.get(CONF_REGION, REGION_BRUSSELS)
        region_name = REGIONAL_DEFAULTS[region]["name"]

        return self.async_show_form(
            step_id="contract_date",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_CONTRACT_START_DATE,
                    default=default_date
                ): DateSelector(DateSelectorConfig()),
            }),
            errors=errors,
            description_placeholders={
                "region": region_name,
                "note": (
                    "⚠️ Important: Cost calculations for consumption BEFORE today "
                    "will use current variable prices (approximation only). "
                    "Accurate cost tracking begins from today forward."
                )
            },
        )

    async def async_step_electricity_type(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle electricity meter type selection."""
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
                "note": "Bi-horaire meters have separate peak (day) and off-peak (night/weekend) consumption tracking."
            },
        )

    async def async_step_electricity_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle electricity P1 sensor configuration."""
        errors = {}
        meter_type = self.config_data[CONF_METER_TYPE]

        if user_input is not None:
            # Validate sensors exist
            validation_ok = True
            
            if meter_type == METER_TYPE_BI_HORAIRE:
                if not self.hass.states.get(user_input["peak_sensor"]):
                    errors["peak_sensor"] = "entity_not_found"
                    validation_ok = False
                if not self.hass.states.get(user_input["offpeak_sensor"]):
                    errors["offpeak_sensor"] = "entity_not_found"
                    validation_ok = False
                
                if validation_ok:
                    self.config_data["elec_peak_sensor"] = user_input["peak_sensor"]
                    self.config_data["elec_offpeak_sensor"] = user_input["offpeak_sensor"]
                    self.config_data["elec_peak_baseline"] = user_input["peak_baseline"]
                    self.config_data["elec_offpeak_baseline"] = user_input["offpeak_baseline"]
            else:
                if not self.hass.states.get(user_input["total_sensor"]):
                    errors["total_sensor"] = "entity_not_found"
                    validation_ok = False
                
                if validation_ok:
                    self.config_data["elec_total_sensor"] = user_input["total_sensor"]
                    self.config_data["elec_total_baseline"] = user_input["total_baseline"]
            
            if validation_ok:
                return await self.async_step_solar_export()

        if meter_type == METER_TYPE_BI_HORAIRE:
            schema = vol.Schema({
                vol.Required("peak_sensor"): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Required("peak_baseline"): NumberSelector(
                    NumberSelectorConfig(
                        unit_of_measurement="kWh",
                    )
                ),
                vol.Required("offpeak_sensor"): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Required("offpeak_baseline"): NumberSelector(
                    NumberSelectorConfig(
                        unit_of_measurement="kWh",
                    )
                ),
            })
            description = (
                "Enter your P1 meter sensors for peak (day) and off-peak (night/weekend) consumption, "
                "and the meter readings from your contract start date."
            )
        else:
            schema = vol.Schema({
                vol.Required("total_sensor"): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Required("total_baseline"): NumberSelector(
                    NumberSelectorConfig(
                        unit_of_measurement="kWh",
                    )
                ),
            })
            description = (
                "Enter your P1 meter sensor for total consumption "
                "and the meter reading from your contract start date."
            )

        return self.async_show_form(
            step_id="electricity_sensors",
            data_schema=schema,
            errors=errors,
            description_placeholders={"note": description},
        )

    async def async_step_solar_export(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle solar export configuration."""
        errors = {}

        if user_input is not None:
            _LOGGER.debug("Solar export user_input: %s", user_input)
            
            try:
                has_solar = user_input.get("has_solar", False)
                self.config_data["has_solar"] = has_solar
                
                if has_solar:
                    # Validate export sensor exists
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
                    # No solar, proceed to electricity costs
                    _LOGGER.debug("No solar selected, proceeding to electricity costs")
                    return await self.async_step_electricity_costs()
            except Exception as err:
                _LOGGER.error("Error in solar_export step: %s", err, exc_info=True)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="solar_export",
            data_schema=vol.Schema({
                vol.Required("has_solar", default=False): BooleanSelector(),
                vol.Optional("export_sensor"): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional("export_baseline", default=0): NumberSelector(
                    NumberSelectorConfig(
                        unit_of_measurement="kWh",
                    )
                ),
            }),
            errors=errors,
            description_placeholders={
                "note": (
                    "If you have solar panels, the integration will track injection revenue "
                    "and calculate net electricity costs."
                )
            },
        )

    async def async_step_electricity_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle electricity cost configuration."""
        if user_input is not None:
            self.config_data["elec_costs"] = user_input
            return await self.async_step_gas_config()

        meter_type = self.config_data[CONF_METER_TYPE]

        if meter_type == METER_TYPE_BI_HORAIRE:
            schema = vol.Schema({
                vol.Required(COST_GREEN_CERT, default=0.0275): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_DIST_PEAK, default=0.0941): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_DIST_OFFPEAK, default=0.0706): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_TRANSMISSION, default=0.0225): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_COTISATION, default=0.00204): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_ACCISE, default=0.05033): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_FIXED_MONTHLY, default=14.05): NumberSelector(
                    NumberSelectorConfig()
                ),
            })
        else:
            schema = vol.Schema({
                vol.Required(COST_GREEN_CERT, default=0.0275): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_DIST_SINGLE, default=0.0823): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_TRANSMISSION, default=0.0225): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_COTISATION, default=0.00204): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_ACCISE, default=0.05033): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_FIXED_MONTHLY, default=14.05): NumberSelector(
                    NumberSelectorConfig()
                ),
            })

        return self.async_show_form(
            step_id="electricity_costs",
            data_schema=schema,
            description_placeholders={
                "note": (
                    "Enter your fixed electricity costs from your ENGIE contract (pages 21-22). "
                    "All values are in EUR/kWh except fixed monthly cost (EUR/month). "
                    "You can update these values later via integration options."
                )
            },
        )

    async def async_step_gas_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle gas configuration."""
        errors = {}

        if user_input is not None:
            has_gas = user_input["has_gas"]
            self.config_data["has_gas"] = has_gas
            
            if has_gas:
                self.config_data["gas_baseline_m3"] = user_input["gas_baseline"]
                self.config_data["gas_current_m3"] = user_input.get("gas_current", user_input["gas_baseline"])
                self.config_data["gas_conversion"] = user_input.get("gas_conversion")
                return await self.async_step_gas_costs()
            else:
                return await self._async_create_entry()

        # Get regional default gas conversion
        region = self.config_data[CONF_REGION]
        default_conversion = REGIONAL_DEFAULTS[region]["gas_conversion"]
        grid_operator = REGIONAL_DEFAULTS[region]["grid_operator"]

        return self.async_show_form(
            step_id="gas_config",
            data_schema=vol.Schema({
                vol.Required("has_gas", default=True): BooleanSelector(),
                vol.Optional("gas_baseline", default=0): NumberSelector(
                    NumberSelectorConfig(
                        unit_of_measurement="m³",
                    )
                ),
                vol.Optional("gas_current", default=0): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=999999,
                        unit_of_measurement="m³",
                    )
                ),
                vol.Optional("gas_conversion", default=default_conversion): NumberSelector(
                    NumberSelectorConfig(
                        unit_of_measurement="kWh/m³",
                    )
                ),
            }),
            errors=errors,
            description_placeholders={
                "grid_operator": grid_operator,
                "default_conversion": str(default_conversion),
                "note": (
                    f"Enter your gas meter baseline reading from contract start date, "
                    f"and your current reading today. If current reading is the same as baseline, "
                    f"leave it at 0 (it will default to baseline). "
                    f"Default conversion factor for {grid_operator}: {default_conversion} kWh/m³"
                )
            },
        )

    async def async_step_gas_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle gas cost configuration."""
        if user_input is not None:
            self.config_data["gas_costs"] = user_input
            return await self._async_create_entry()

        return self.async_show_form(
            step_id="gas_costs",
            data_schema=vol.Schema({
                vol.Required(COST_GAS_DISTRIBUTION, default=0.01949): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_GAS_TRANSMISSION, default=0.00165): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_GAS_COTISATION, default=0.00106): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_GAS_ACCISE, default=0.00872): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_GAS_FIXED_MONTHLY, default=7.57): NumberSelector(
                    NumberSelectorConfig()
                ),
            }),
            description_placeholders={
                "note": (
                    "Enter your fixed gas costs from your ENGIE contract (pages 25-26). "
                    "All values are in EUR/kWh except fixed monthly cost (EUR/month). "
                    "You can update these values later via integration options."
                )
            },
        )

    async def _async_create_entry(self) -> FlowResult:
        """Create the config entry."""
        # Build final config structure
        meter_type = self.config_data[CONF_METER_TYPE]
        region = self.config_data[CONF_REGION]
        
        # Electricity import config
        elec_import = {
            CONF_P1_SENSORS: {},
            CONF_BASELINE_READINGS: {},
        }
        
        if meter_type == METER_TYPE_BI_HORAIRE:
            elec_import[CONF_P1_SENSORS] = {
                SENSOR_PEAK: self.config_data["elec_peak_sensor"],
                SENSOR_OFFPEAK: self.config_data["elec_offpeak_sensor"],
            }
            elec_import[CONF_BASELINE_READINGS] = {
                SENSOR_PEAK: self.config_data["elec_peak_baseline"],
                SENSOR_OFFPEAK: self.config_data["elec_offpeak_baseline"],
            }
        else:
            elec_import[CONF_P1_SENSORS] = {
                SENSOR_TOTAL: self.config_data["elec_total_sensor"],
            }
            elec_import[CONF_BASELINE_READINGS] = {
                SENSOR_TOTAL: self.config_data["elec_total_baseline"],
            }
        
        # Electricity export config
        elec_export = {
            CONF_ENABLED: self.config_data.get("has_solar", False),
        }
        
        if self.config_data.get("has_solar"):
            elec_export[CONF_P1_SENSORS] = {
                SENSOR_TOTAL: self.config_data["export_sensor"],
            }
            elec_export[CONF_BASELINE_READINGS] = {
                SENSOR_TOTAL: self.config_data["export_baseline"],
            }
        
        # Electricity config
        electricity = {
            CONF_METER_TYPE: meter_type,
            CONF_IMPORT: elec_import,
            CONF_EXPORT: elec_export,
            CONF_COSTS: self.config_data["elec_costs"],
        }
        
        # Gas config
        gas = {
            CONF_ENABLED: self.config_data.get("has_gas", False),
        }
        
        if self.config_data.get("has_gas"):
            gas[CONF_BASELINE_READING_M3] = self.config_data["gas_baseline_m3"]
            gas["current_reading_m3"] = self.config_data.get("gas_current_m3", self.config_data["gas_baseline_m3"])
            gas[CONF_CONVERSION_FACTOR] = self.config_data["gas_conversion"]
            gas[CONF_COSTS] = self.config_data["gas_costs"]
        
        # Final config
        config = {
            CONF_REGION: region,
            CONF_CONTRACT_START_DATE: self.config_data[CONF_CONTRACT_START_DATE].isoformat(),
            CONF_ELECTRICITY: electricity,
            CONF_GAS: gas,
        }
        
        # Create title with region
        region_name = REGIONAL_DEFAULTS[region]["name"]
        title = f"Belgium Energy Costs ({region_name})"
        
        return self.async_create_entry(
            title=title,
            data=config,
        )

    async def _check_engie_integration(self) -> dict[str, Any]:
        """Check if ENGIE Belgium integration is installed and sensors exist."""
        result = {"installed": False, "missing_sensors": []}
        
        # Check for ENGIE sensors
        if self.hass.states.get(ENGIE_SENSOR_ELEC_PEAK):
            result["installed"] = True
        
        return result

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return BelgiumEnergyCostsOptionsFlow(config_entry)


class BelgiumEnergyCostsOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Belgium Energy Costs."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        return await self.async_step_menu()

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show options menu."""
        return self.async_show_menu(
            step_id="menu",
            menu_options=["electricity_costs", "gas_costs", "gas_reading"],
        )

    async def async_step_electricity_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Update electricity costs."""
        if user_input is not None:
            # Update config entry
            new_data = dict(self.config_entry.data)
            new_data[CONF_ELECTRICITY][CONF_COSTS] = user_input
            
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
            )
            
            return self.async_create_entry(title="", data={})

        current_costs = self.config_entry.data[CONF_ELECTRICITY][CONF_COSTS]
        meter_type = self.config_entry.data[CONF_ELECTRICITY][CONF_METER_TYPE]

        if meter_type == METER_TYPE_BI_HORAIRE:
            schema = vol.Schema({
                vol.Required(COST_GREEN_CERT, default=current_costs.get(COST_GREEN_CERT, 0.0275)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_DIST_PEAK, default=current_costs.get(COST_DIST_PEAK, 0.0941)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_DIST_OFFPEAK, default=current_costs.get(COST_DIST_OFFPEAK, 0.0706)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_TRANSMISSION, default=current_costs.get(COST_TRANSMISSION, 0.0225)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_COTISATION, default=current_costs.get(COST_COTISATION, 0.00204)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_ACCISE, default=current_costs.get(COST_ACCISE, 0.05033)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_FIXED_MONTHLY, default=current_costs.get(COST_FIXED_MONTHLY, 14.05)): NumberSelector(
                    NumberSelectorConfig()
                ),
            })
        else:
            schema = vol.Schema({
                vol.Required(COST_GREEN_CERT, default=current_costs.get(COST_GREEN_CERT, 0.0275)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_DIST_SINGLE, default=current_costs.get(COST_DIST_SINGLE, 0.0823)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_TRANSMISSION, default=current_costs.get(COST_TRANSMISSION, 0.0225)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_COTISATION, default=current_costs.get(COST_COTISATION, 0.00204)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_ACCISE, default=current_costs.get(COST_ACCISE, 0.05033)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_FIXED_MONTHLY, default=current_costs.get(COST_FIXED_MONTHLY, 14.05)): NumberSelector(
                    NumberSelectorConfig()
                ),
            })

        return self.async_show_form(
            step_id="electricity_costs",
            data_schema=schema,
            description_placeholders={
                "note": "Update your electricity costs from your new ENGIE contract (pages 21-22)."
            },
        )

    async def async_step_gas_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Update gas costs."""
        if not self.config_entry.data[CONF_GAS][CONF_ENABLED]:
            return self.async_abort(reason="gas_not_enabled")

        if user_input is not None:
            # Update config entry
            new_data = dict(self.config_entry.data)
            new_data[CONF_GAS][CONF_COSTS] = user_input
            
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data,
            )
            
            return self.async_create_entry(title="", data={})

        current_costs = self.config_entry.data[CONF_GAS][CONF_COSTS]

        return self.async_show_form(
            step_id="gas_costs",
            data_schema=vol.Schema({
                vol.Required(COST_GAS_DISTRIBUTION, default=current_costs.get(COST_GAS_DISTRIBUTION, 0.01949)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_GAS_TRANSMISSION, default=current_costs.get(COST_GAS_TRANSMISSION, 0.00165)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_GAS_COTISATION, default=current_costs.get(COST_GAS_COTISATION, 0.00106)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_GAS_ACCISE, default=current_costs.get(COST_GAS_ACCISE, 0.00872)): NumberSelector(
                    NumberSelectorConfig()
                ),
                vol.Required(COST_GAS_FIXED_MONTHLY, default=current_costs.get(COST_GAS_FIXED_MONTHLY, 7.57)): NumberSelector(
                    NumberSelectorConfig()
                ),
            }),
            description_placeholders={
                "note": "Update your gas costs from your new ENGIE contract (pages 25-26)."
            },
        )

    async def async_step_gas_reading(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Update gas meter reading."""
        if not self.config_entry.data[CONF_GAS][CONF_ENABLED]:
            return self.async_abort(reason="gas_not_enabled")

        if user_input is not None:
            # Call the update gas reading service
            await self.hass.services.async_call(
                DOMAIN,
                "update_gas_reading",
                {"reading": user_input["gas_reading"]},
            )
            
            return self.async_create_entry(title="", data={})

        # Get current reading from number entity
        current_reading = 0
        gas_entity = f"number.{DOMAIN}_gas_meter_reading"
        state = self.hass.states.get(gas_entity)
        if state:
            try:
                current_reading = float(state.state)
            except (ValueError, TypeError):
                pass

        return self.async_show_form(
            step_id="gas_reading",
            data_schema=vol.Schema({
                vol.Required("gas_reading", default=current_reading): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=999999,
                        step=0.001,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="m³",
                    )
                ),
            }),
            description_placeholders={
                "note": "Update your current gas meter reading (monthly on the 1st)."
            },
        )
