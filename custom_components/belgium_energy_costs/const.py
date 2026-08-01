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
# User's estimate of annual PV generation (kWh/year), stored under the
# electricity export config. Feeds the seasonal year-end projection; 0 = no PV
# term (the projection degrades to a seasonal load-only model).
CONF_PV_ANNUAL_KWH = "pv_annual_generation_kwh"

# Regions
REGION_BRUSSELS = "brussels"
REGION_FLANDERS = "flanders"
REGION_WALLONIA = "wallonia"

# Regional configuration
REGIONAL_DEFAULTS = {
    REGION_BRUSSELS: {
        "name": "Brussels",
        "grid_operator": "SIBELGA",
        # Calibrated against a full 359-day SIBELGA gas bill (1481 m³ → 16865 kWh).
        "gas_conversion": 11.39,
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
        "grid_operator": "ORES (default) / RESA / AIEG / AIESH / Régie de Wavre",
        # ORES default; calibrate from a real Walloon bill like Brussels (11.39).
        "gas_conversion": 11.0,
        "supported": True,
        "description": "Walloon Region — defaults from ORES (largest DSO); other DSOs adjustable in setup",
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
DEFAULT_GAS_CONVERSION = 11.39  # kWh/m³ for Brussels/SIBELGA (calibrated from a full annual bill)
DEFAULT_DAYS_PER_MONTH = 30.44

# Per-region default cost components (EUR/kWh, except *_fixed_monthly in EUR/month).
# These pre-fill the setup flow; every value remains editable per user/contract/DSO.
# Brussels = SIBELGA (the original calibrated set). Wallonia = ORES (the largest DSO,
# ~75% of Wallonia), sourced from the ENGIE Wallonia "prices & conditions" sheets.
# Any region without an entry falls back to Brussels.
#
# Other Walloon DSO electricity distribution (c€/kWh — peak / off-peak / single / terme-fixe €/yr):
#   AIEG          12.05 / 6.66 / 10.87 / 19.49     AIESH  15.17 / 8.21 / 13.64 / 17.92
#   TECTEO-RESA   12.20 / 7.01 / 11.06 / 26.50     Régie de Wavre 13.78 / 7.84 / 12.48 / 26.44
# Other Walloon DSO gas distribution (Moyenne tier — proportional c€/kWh / terme-fixe €/yr):
#   TECTEO-RESA   2.529 / 122.05   (ORES: 2.206 / 140.93)
REGION_COST_DEFAULTS = {
    REGION_BRUSSELS: {
        "elec": {
            COST_GREEN_CERT: 0.0275,
            COST_DIST_PEAK: 0.0941,
            COST_DIST_OFFPEAK: 0.0706,
            COST_DIST_SINGLE: 0.0823,
            COST_TRANSMISSION: 0.0225,
            COST_COTISATION: 0.00204,
            COST_ACCISE: 0.05033,
            COST_FIXED_MONTHLY: 14.05,
        },
        "gas": {
            COST_GAS_DISTRIBUTION: 0.01949,
            COST_GAS_TRANSMISSION: 0.00165,
            COST_GAS_COTISATION: 0.00106,
            COST_GAS_ACCISE: 0.00872,
            COST_GAS_FIXED_MONTHLY: 7.57,
        },
    },
    REGION_WALLONIA: {  # ORES (largest Walloon DSO); from ENGIE Wallonia price sheets
        "elec": {
            COST_GREEN_CERT: 0.03095,      # "coûts énergie verte" 3.095 c€/kWh
            COST_DIST_PEAK: 0.1327,        # distribution heures pleines
            COST_DIST_OFFPEAK: 0.0739,     # distribution heures creuses
            COST_DIST_SINGLE: 0.1198,      # distribution normal (single tariff)
            COST_TRANSMISSION: 0.0274,     # transport
            COST_COTISATION: 0.00204,      # cotisation fédérale (national)
            COST_ACCISE: 0.05033,          # accise fédérale 0-20,000 kWh (national)
            COST_FIXED_MONTHLY: 6.93,      # ORES terme fixe 14.10/yr + ENGIE redevance 69/yr, /12
        },
        "gas": {
            COST_GAS_DISTRIBUTION: 0.02206,    # ORES "Moyenne" tier (5,001-150,000 kWh/yr)
            COST_GAS_TRANSMISSION: 0.00165,    # transport 0.165 c€/kWh
            COST_GAS_COTISATION: 0.00106,
            COST_GAS_ACCISE: 0.00872,          # accise 0-12,000 kWh
            COST_GAS_FIXED_MONTHLY: 16.74,     # ORES gas terme fixe 140.93/yr + ENGIE 60/yr, /12
        },
    },
}

# Config keys for user-selected ENGIE sensor entity IDs
# These are stored in the config entry and passed to sensors at runtime.
# The ENGIE integration changed its entity naming scheme in v0.8.2 — entity IDs
# now include the account ID and EAN number and are therefore user-specific.
CONF_ENGIE_ELEC_PEAK = "engie_elec_peak_sensor"
CONF_ENGIE_ELEC_OFFPEAK = "engie_elec_offpeak_sensor"
CONF_ENGIE_ELEC_INJECTION = "engie_elec_injection_sensor"
CONF_ENGIE_GAS = "engie_gas_sensor"

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
SENSOR_ELEC_PROJECTED_YEAR = "electricity_projected_year_end_cost"
SENSOR_GAS_PROJECTED_YEAR = "gas_projected_year_end_cost"
SENSOR_TOTAL_PROJECTED_YEAR = "total_projected_year_end_cost"


def get_gas_meter_entity_id(entry_id: str) -> str:
    """Return the gas meter number entity_id scoped to a config entry.

    The entry_id (a ULID) is lowercased so the resulting entity_id only
    contains valid characters (a-z, 0-9, underscore). ULIDs are
    case-insensitive so this is safe.
    """
    return f"number.{DOMAIN}_{entry_id.lower()}_gas_meter_reading"


def get_close_date_entity_id(entry_id: str, utility: str) -> str:
    """Return the contract-year close-date date entity_id for a utility.

    *utility* is "elec" or "gas". Used by the dashboard date picker and read
    by the close service when no explicit period_end is supplied.
    """
    return f"date.{DOMAIN}_{entry_id.lower()}_{utility}_close_date"
