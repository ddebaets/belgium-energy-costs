"""Constants for Belgium Energy Costs integration."""

DOMAIN = "belgium_energy_costs"

# Configuration keys
CONF_CONTRACT_START_DATE = "contract_start_date"
CONF_REGION = "region"
CONF_ELECTRICITY = "electricity"
CONF_GAS = "gas"
CONF_METER_TYPE = "meter_type"
CONF_IMPORT = "import"
CONF_EXPORT = "export"
CONF_ENABLED = "enabled"
CONF_P1_SENSORS = "p1_sensors"
CONF_BASELINE_READINGS = "baseline_readings"
CONF_COSTS = "costs"
CONF_CONVERSION_FACTOR = "conversion_factor"
CONF_BASELINE_READING_M3 = "baseline_reading_m3"

# Regions
REGION_BRUSSELS = "brussels"
REGION_FLANDERS = "flanders"
REGION_WALLONIA = "wallonia"

# Regional configuration
REGIONAL_DEFAULTS = {
    REGION_BRUSSELS: {
        "name": "Brussels",
        "grid_operator": "SIBELGA",
        "gas_conversion": 11.2,
        "supported": True,
        "description": "Brussels-Capital Region (SIBELGA)",
    },
    REGION_FLANDERS: {
        "name": "Flanders",
        "grid_operator": "Fluvius",
        "gas_conversion": 11.0,  # Average - needs community verification
        "supported": False,
        "description": "Flemish Region (Fluvius)",
    },
    REGION_WALLONIA: {
        "name": "Wallonia",
        "grid_operator": "ORES/RESA/AIEG/AIESH",
        "gas_conversion": 11.0,  # Average - needs community verification
        "supported": False,
        "description": "Walloon Region (ORES, RESA, AIEG, AIESH, REW)",
    },
}

# Meter types
METER_TYPE_SINGLE = "single"
METER_TYPE_BI_HORAIRE = "bi_horaire"

# P1 sensor keys
SENSOR_TOTAL = "total"
SENSOR_PEAK = "peak"
SENSOR_OFFPEAK = "offpeak"

# Electricity cost components
COST_GREEN_CERT = "green_certificates"
COST_DIST_PEAK = "distribution_peak"
COST_DIST_OFFPEAK = "distribution_offpeak"
COST_DIST_SINGLE = "distribution"
COST_TRANSMISSION = "transmission"
COST_COTISATION = "cotisation"
COST_ACCISE = "accise_federale"
COST_FIXED_MONTHLY = "fixed_monthly"

# Gas cost components
COST_GAS_DISTRIBUTION = "distribution"
COST_GAS_TRANSMISSION = "transmission"
COST_GAS_COTISATION = "cotisation"
COST_GAS_ACCISE = "accise_federale"
COST_GAS_FIXED_MONTHLY = "fixed_monthly"

# Default values
DEFAULT_GAS_CONVERSION = 11.2  # kWh/m³ for Brussels/SIBELGA
DEFAULT_DAYS_PER_MONTH = 30.44

# ENGIE Belgium integration sensor names
ENGIE_SENSOR_ELEC_PEAK = "sensor.engie_belgium_electricity_peak_offtake_price"
ENGIE_SENSOR_ELEC_OFFPEAK = "sensor.engie_belgium_electricity_off_peak_offtake_price"
ENGIE_SENSOR_ELEC_INJECTION = "sensor.engie_belgium_electricity_injection_price"
ENGIE_SENSOR_GAS = "sensor.engie_belgium_gas_offtake_price"

# Sensor unique ID suffixes
SENSOR_MONTHS_SINCE_START = "months_since_contract_start"
SENSOR_TOTAL_ELEC_PEAK = "total_electricity_cost_peak"
SENSOR_TOTAL_ELEC_OFFPEAK = "total_electricity_cost_off_peak"
SENSOR_TOTAL_ELEC_SINGLE = "total_electricity_cost"
SENSOR_TOTAL_ELEC_INJECTION = "total_electricity_injection_price"
SENSOR_ELEC_PEAK_OFFPEAK_SAVINGS = "electricity_peak_vs_off_peak_savings"
SENSOR_TOTAL_GAS = "total_gas_cost"
SENSOR_GAS_METER_KWH = "gas_meter_reading_kwh"
SENSOR_GAS_CONSUMPTION = "gas_total_consumption_since_contract_start"
SENSOR_GAS_AVG_MONTHLY = "gas_average_monthly_consumption"
SENSOR_ELEC_PEAK_CONSUMPTION = "electricity_peak_consumption_since_contract_start"
SENSOR_ELEC_OFFPEAK_CONSUMPTION = "electricity_off_peak_consumption_since_contract_start"
SENSOR_ELEC_SINGLE_CONSUMPTION = "electricity_consumption_since_contract_start"
SENSOR_ELEC_EXPORT_TOTAL = "electricity_total_export_since_contract_start"
SENSOR_ELEC_EXPORT_REVENUE = "electricity_injection_revenue_since_contract_start"
SENSOR_ELEC_TOTAL_COST = "electricity_total_cost_since_contract_start"
SENSOR_ELEC_NET_COST = "electricity_net_cost_since_contract_start"
SENSOR_ELEC_ANNUAL_COST = "electricity_estimated_annual_cost"
SENSOR_ELEC_ANNUAL_REVENUE = "electricity_estimated_annual_injection_revenue"
SENSOR_GAS_TOTAL_COST = "gas_total_cost_since_contract_start"
SENSOR_GAS_ANNUAL_COST = "gas_estimated_annual_cost"
SENSOR_TOTAL_ENERGY_COST = "total_energy_cost_since_contract_start"
SENSOR_TOTAL_ANNUAL_COST = "total_estimated_annual_energy_cost"


def get_gas_meter_entity_id(entry_id: str) -> str:
    """Return the gas meter number entity_id scoped to a config entry.

    The entry_id (a ULID) is lowercased so the resulting entity_id only
    contains valid characters (a-z, 0-9, underscore). ULIDs are
    case-insensitive so this is safe.
    """
    return f"number.{DOMAIN}_{entry_id.lower()}_gas_meter_reading"
