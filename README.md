# Belgium Energy Costs

Complete energy cost tracking for Belgium, combining variable supplier prices with regional fixed costs (distribution, transmission, taxes).

## Features

✅ **Total Real Costs** - Combines variable energy prices (from your supplier integration) with all fixed costs (distribution, transmission, taxes, monthly fees)  
✅ **Consumption Tracking** - Tracks electricity and gas consumption since contract start  
✅ **Solar Export Support** - Calculates injection revenue and net electricity costs  
✅ **Annual Projections** - Estimates yearly energy costs based on consumption patterns  
✅ **Bi-horaire Support** - Full support for day/night tariff meters  
✅ **Auto-Updates** - Variable prices fetched automatically from hass-engie-be integration  
✅ **Multi-Region** - Designed for all Belgian regions (Brussels fully supported)

## Supported Regions

The integration is designed to work across all Belgian regions, with region-specific defaults for gas conversion factors and grid operators.

### Current Status:

| Region | Grid Operator | Status | Gas Conversion |
|--------|---------------|--------|----------------|
| **🟢 Brussels** | SIBELGA | ✅ **Fully Supported** | 11.2 kWh/m³ |
| **🟡 Flanders** | Fluvius | ⚠️ **Coming Soon** | ~11.0 kWh/m³ |
| **🟡 Wallonia** | ORES/RESA/AIEG/AIESH | ⚠️ **Coming Soon** | ~11.0 kWh/m³ |

### Brussels (SIBELGA) - ✅ Fully Supported
Complete support with verified cost structures and defaults. All features tested and working.

### Flanders (Fluvius) - ⚠️ Coming Soon
Basic support available, but regional cost defaults need community verification. The integration will work, but you'll need to manually verify cost values from your contract match Flanders-specific rates.

**Help wanted!** If you're in Flanders, please [open an issue](https://github.com/ddebaets/belgium-energy-costs/issues) with your ENGIE contract details (pages 21-22 for electricity, 25-26 for gas) so we can add verified defaults.

### Wallonia (ORES/RESA/AIEG/AIESH) - ⚠️ Coming Soon  
Basic support available, but regional cost defaults need community verification. The integration will work, but you'll need to manually verify cost values from your contract match Wallonia-specific rates.

**Help wanted!** If you're in Wallonia, please [open an issue](https://github.com/ddebaets/belgium-energy-costs/issues) with your ENGIE contract details so we can add verified defaults.

### Want to Help?
We need community contributions to support all Belgian regions! If you live in Flanders or Wallonia:
1. Open an issue on GitHub
2. Share your ENGIE contract pages (21-22 for electricity, 25-26 for gas)
3. We'll add verified defaults for your region!

**Note:** Variable ENGIE prices are the same across all regions (supplier-level), but fixed costs (distribution, transmission, some taxes) may vary by grid operator.  

## Installation

### Via HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the 3 dots in the top right → "Custom repositories"
4. Add repository: `https://github.com/ddebaets/belgium-energy-costs`
5. Category: Integration
6. Click "Add"
7. Search for "Belgium Energy Costs"
8. Click "Download"
9. Restart Home Assistant
10. Go to Settings → Devices & Services → Add Integration
11. Search "Belgium Energy Costs"
12. Follow the 8-step configuration wizard

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/ddebaets/belgium-energy-costs/releases)
2. Extract the `belgium_energy_costs` folder to your `/config/custom_components/` directory
3. Restart Home Assistant
4. Go to Settings → Devices & Services → Add Integration
5. Search "Belgium Energy Costs"
6. Follow the 8-step configuration wizard

## Prerequisites

**Required:**
1. [hass-engie-be](https://github.com/myTselection/hass-engie-be) integration installed and configured
2. P1 meter integration providing consumption sensors

**Optional:**
3. Solar panels with export tracking

## Installation

### HACS (Recommended)

1. Open HACS → Integrations
2. Click ⋮ (three dots) → Custom repositories
3. Add repository: `https://github.com/ddebaets/belgium-energy-costs`
4. Category: `Integration`
5. Click **Belgium Energy Costs** → Install
6. Restart Home Assistant

### Manual

1. Copy `custom_components/belgium_energy_costs` to your HA `custom_components` directory
2. Restart Home Assistant

## Configuration

Add to `configuration.yaml`:

### Example 1: Bi-horaire Electricity + Gas + Solar

```yaml
belgium_energy_costs:
  contract_start_date: "2025-06-03"
  
  electricity:
    meter_type: bi_horaire  # or "single" for single tariff
    
    # Consumption (import)
    import:
      p1_sensors:
        peak: sensor.p1_meter_energy_import_tariff_1
        offpeak: sensor.p1_meter_energy_import_tariff_2
      baseline_readings:  # Your meter readings at contract start
        peak: 7471
        offpeak: 9331
    
    # Solar production (export) - OPTIONAL
    export:
      enabled: true
      p1_sensors:
        total: sensor.p1_meter_energy_export_total
      baseline_readings:
        total: 1250
    
    # Fixed costs (from your ENGIE contract pages 21-22)
    costs:
      green_certificates: 0.0275      # EUR/kWh
      distribution_peak: 0.0941       # EUR/kWh
      distribution_offpeak: 0.0706    # EUR/kWh
      transmission: 0.0225            # EUR/kWh
      cotisation: 0.00204             # EUR/kWh
      accise_federale: 0.05033        # EUR/kWh
      fixed_monthly: 14.05            # EUR/month
  
  gas:
    enabled: true
    baseline_reading_m3: 12096        # Your gas meter at contract start
    conversion_factor: 11.2           # kWh/m³ (Brussels/SIBELGA: 11.2)
    costs:  # From your ENGIE contract pages 25-26
      distribution: 0.01949           # EUR/kWh
      transmission: 0.00165           # EUR/kWh
      cotisation: 0.00106             # EUR/kWh
      accise_federale: 0.00872        # EUR/kWh
      fixed_monthly: 7.57             # EUR/month
```

### Example 2: Single Tariff Electricity, No Gas, No Solar

```yaml
belgium_energy_costs:
  contract_start_date: "2024-01-01"
  
  electricity:
    meter_type: single
    
    import:
      p1_sensors:
        total: sensor.p1_meter_energy_import_total
      baseline_readings:
        total: 15420
    
    costs:
      green_certificates: 0.0275
      distribution: 0.0823            # Single tariff uses "distribution" not "distribution_peak"
      transmission: 0.0225
      cotisation: 0.00204
      accise_federale: 0.05033
      fixed_monthly: 14.05
  
  gas:
    enabled: false
```

## Sensors Created

### Always Created:
- `sensor.months_since_contract_start` - Dynamic contract duration

### Electricity (Bi-horaire):
- `sensor.total_electricity_cost_peak` - EUR/kWh (variable + fixed)
- `sensor.total_electricity_cost_off_peak` - EUR/kWh (variable + fixed)
- `sensor.electricity_peak_vs_off_peak_savings` - Savings potential
- `sensor.electricity_peak_consumption_since_contract_start` - kWh
- `sensor.electricity_off_peak_consumption_since_contract_start` - kWh
- `sensor.electricity_total_cost_since_contract_start` - EUR
- `sensor.electricity_estimated_annual_cost` - EUR/year
- `sensor.electricity_average_monthly_consumption` - kWh/month
- `sensor.electricity_average_monthly_cost` - EUR/month

### Electricity (Single Tariff):
- `sensor.total_electricity_cost` - EUR/kWh (variable + fixed)
- `sensor.electricity_consumption_since_contract_start` - kWh
- `sensor.electricity_total_cost_since_contract_start` - EUR
- `sensor.electricity_estimated_annual_cost` - EUR/year
- `sensor.electricity_average_monthly_consumption` - kWh/month
- `sensor.electricity_average_monthly_cost` - EUR/month

### Solar Export (if enabled):
- `sensor.total_electricity_injection_price` - EUR/kWh
- `sensor.electricity_total_export_since_contract_start` - kWh injected
- `sensor.electricity_injection_revenue_since_contract_start` - EUR earned
- `sensor.electricity_net_cost_since_contract_start` - EUR (consumption - revenue)
- `sensor.electricity_estimated_annual_injection_revenue` - EUR/year

### Gas (if enabled):
- `sensor.total_gas_cost` - EUR/kWh (variable + fixed)
- `sensor.gas_consumption_since_contract_start` - m³
- `sensor.gas_consumption_since_contract_start_kwh` - kWh
- `sensor.gas_total_cost_since_contract_start` - EUR
- `sensor.gas_estimated_annual_cost` - EUR/year
- `sensor.gas_average_monthly_consumption` - kWh/month
- `sensor.gas_average_monthly_cost` - EUR/month
- `number.belgium_energy_costs_gas_meter_reading` - Manual gas meter (m³)

### Combined:
- `sensor.total_energy_cost_since_contract_start` - EUR (electricity + gas)
- `sensor.total_estimated_annual_energy_cost` - EUR/year
- `sensor.total_average_monthly_energy_cost` - EUR/month

## Manual Gas Meter Updates

Since most Belgian homes don't have digital gas meters on the P1 port, you'll need to update your gas reading manually each month (recommended: 1st of each month).

**Three methods to update:**

### Method 1: Via Options Flow (Easiest)
1. Settings → Devices & Services
2. Belgium Energy Costs → Configure
3. "Update Gas Meter Reading"
4. Enter current reading (e.g., 13500)
5. Submit ✅

### Method 2: Via Service Call (For Automations)
```yaml
service: belgium_energy_costs.update_gas_reading
data:
  reading: 13500
```

### Method 3: Via Number Entity
1. Developer Tools → States
2. Find: `number.belgium_energy_costs_gas_meter_reading`
3. Set value manually

## Annual Cost Update

When your new energy contract arrives (typically June):

### Via Options Flow (Recommended - No Restart Required!)
1. Settings → Devices & Services
2. Belgium Energy Costs → Configure
3. "Update Electricity Costs" or "Update Gas Costs"
4. Enter new values from contract (pages 21-22 for electricity, 25-26 for gas)
5. Submit ✅
6. Sensors update immediately!

### Via YAML (Alternative)
1. Open `configuration.yaml`
2. Find the `belgium_energy_costs:` section
3. Update the cost values from your new contract
4. Save
5. **Developer Tools → YAML → Check Configuration**
6. Restart Home Assistant

## Energy Dashboard Integration

All sensors are compatible with Home Assistant's Energy Dashboard:

**Electricity:**
- Consumption: Use P1 meter sensors (peak/offpeak or total)
- Cost per kWh: Use `sensor.total_electricity_cost_peak` / `sensor.total_electricity_cost_off_peak`

**Gas:**
- Consumption: Use `sensor.gas_consumption_since_contract_start_kwh`
- Cost per kWh: Use `sensor.total_gas_cost`
- Cost tracking: Use `sensor.gas_total_cost_since_contract_start`

## Dependencies

- [hass-engie-be](https://github.com/myTselection/hass-engie-be) - Fetches variable ENGIE Belgium prices

## Support

- [GitHub Issues](https://github.com/ddebaets/belgium-energy-costs/issues)
- [Home Assistant Community Forum](https://community.home-assistant.io/)

## License

MIT License - See LICENSE file

## Credits

- Variable price data provided by [hass-engie-be](https://github.com/myTselection/hass-engie-be) by @myTselection
- Developed for the Belgian energy market (SIBELGA, Fluvius, ORES)
