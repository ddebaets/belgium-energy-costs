# Belgium Energy Costs

A Home Assistant custom integration that tracks **real-time total energy costs** for Belgian households, combining variable supplier prices from the [hass-engie-be](https://github.com/myTselection/hass-engie-be) integration with the fixed distribution, transmission, and tax components specific to your Belgian grid operator.

## Features

- ⚡ **Real electricity costs** — variable ENGIE price + green certificates + distribution + transmission + taxes, per kWh
- 🔥 **Real gas costs** — variable ENGIE price + distribution + transmission + taxes, per kWh
- 📊 **Consumption tracking** — electricity (peak/off-peak or single) and gas since contract start
- ☀️ **Solar export support** — injection revenue and net electricity cost
- 📅 **Separate contract dates** — electricity and gas contracts can start on different dates
- 📈 **Monthly averages & annual projections** — extrapolated from actual consumption
- 🔄 **Event-driven, not polled** — sensors update instantly when P1 meter or ENGIE prices change
- ⚡ **Debounced batch updates** — rapid P1 meter ticks are absorbed and flushed as a single batch (5 s window), reducing HA event-loop pressure
- 🌍 **Multi-region** — Brussels (fully supported), Flanders and Wallonia (community contributions welcome)

## Supported Regions

| Region | Grid Operator | Status | Gas Conversion |
|--------|---------------|--------|----------------|
| 🟢 **Brussels** | SIBELGA | ✅ Fully Supported | 11.2 kWh/m³ |
| 🟡 **Flanders** | Fluvius | ⚠️ Coming Soon | ~11.0 kWh/m³ |
| 🟡 **Wallonia** | ORES/RESA/AIEG/AIESH | ⚠️ Coming Soon | ~11.0 kWh/m³ |

> **Help wanted!** If you're in Flanders or Wallonia, please [open an issue](https://github.com/ddebaets/belgium-energy-costs/issues) with your ENGIE contract details (pages 21–22 for electricity, 25–26 for gas) so we can add verified defaults for your region.

## Prerequisites

1. [hass-engie-be](https://github.com/myTselection/hass-engie-be) — provides real-time variable ENGIE prices
2. A P1 meter integration — provides electricity consumption sensors
3. *(Optional)* Solar panels with a grid export sensor

## Installation

### Via HACS (Recommended)

1. Open HACS → Integrations
2. Click ⋮ → Custom repositories
3. Add `https://github.com/ddebaets/belgium-energy-costs` — Category: Integration
4. Search **Belgium Energy Costs** → Download
5. Restart Home Assistant
6. Settings → Devices & Services → Add Integration → **Belgium Energy Costs**

### Manual

1. Copy `custom_components/belgium_energy_costs/` to your HA `/config/custom_components/` directory
2. Restart Home Assistant
3. Settings → Devices & Services → Add Integration → **Belgium Energy Costs**

## Setup Wizard (8 steps)

| Step | What you configure |
|------|--------------------|
| 1 | Region (Brussels / Flanders / Wallonia) |
| 2 | Contract start dates — electricity and gas separately |
| 3 | Electricity meter type (bi-horaire or single tariff) |
| 4 | P1 meter sensors + baseline readings at contract start |
| 5 | Solar export sensor (optional) |
| 6 | Electricity fixed costs (from ENGIE contract pages 21–22) |
| 7 | Gas meter readings (baseline at contract start + today's reading) + conversion factor |
| 8 | Gas fixed costs (from ENGIE contract pages 25–26) |

All cost values can be updated later via **Settings → Devices & Services → Belgium Energy Costs → Configure** — no restart required.

## Sensors Created

### Always created
| Sensor | Unit | Description |
|--------|------|-------------|
| Months Since Contract Start | — | Dynamic contract duration |

### Electricity — bi-horaire
| Sensor | Unit | Description |
|--------|------|-------------|
| Total Electricity Cost Peak | €/kWh | ENGIE variable + all fixed components (day tariff) |
| Total Electricity Cost Off-Peak | €/kWh | ENGIE variable + all fixed components (night/weekend tariff) |
| Electricity Peak vs Off-Peak Savings | €/kWh | Price difference between tariffs |
| Electricity Peak Consumption Since Contract Start | kWh | — |
| Electricity Off-Peak Consumption Since Contract Start | kWh | — |
| Electricity Total Cost Since Contract Start | € | Energy + fixed monthly costs |
| Electricity Estimated Annual Cost | € | Extrapolated from actual consumption |
| Electricity Average Monthly Consumption | kWh | — |
| Electricity Average Monthly Cost | € | — |

### Electricity — single tariff
| Sensor | Unit | Description |
|--------|------|-------------|
| Total Electricity Cost | €/kWh | ENGIE variable + all fixed components |
| Electricity Consumption Since Contract Start | kWh | — |
| Electricity Total Cost Since Contract Start | € | — |
| Electricity Estimated Annual Cost | € | — |
| Electricity Average Monthly Consumption | kWh | — |
| Electricity Average Monthly Cost | € | — |

### Solar export (if enabled)
| Sensor | Unit | Description |
|--------|------|-------------|
| Total Electricity Injection Price | €/kWh | What ENGIE pays per injected kWh |
| Electricity Total Export Since Contract Start | kWh | — |
| Electricity Injection Revenue Since Contract Start | € | — |
| Electricity Net Cost Since Contract Start | € | Consumption cost minus injection revenue |
| Electricity Estimated Annual Injection Revenue | € | — |

### Gas (if enabled)
| Sensor | Unit | Description |
|--------|------|-------------|
| Total Gas Cost | €/kWh | ENGIE variable + all fixed per-kWh components |
| Gas Consumption Since Contract Start | m³ | — |
| Gas Consumption Since Contract Start (kWh) | kWh | Using your conversion factor |
| Gas Total Cost Since Contract Start | € | Energy + fixed monthly costs |
| Gas Estimated Annual Cost | € | Extrapolated from actual consumption |
| Gas Average Monthly Consumption | kWh | — |
| Gas Average Monthly Cost | € | — |

### Combined
| Sensor | Unit | Description |
|--------|------|-------------|
| Total Energy Cost Since Contract Start | € | Electricity + gas |
| Total Estimated Annual Energy Cost | € | Electricity + gas annualised |
| Total Average Monthly Energy Cost | € | — |

### Number entity
| Entity | Unit | Description |
|--------|------|-------------|
| Gas Meter Reading | m³ | Manual gas meter — update monthly |

## Updating Gas Meter Reading

Belgian gas meters are typically not connected to the P1 port, so you update the reading manually (recommended: 1st of each month).

**Via options flow** (easiest):
Settings → Devices & Services → Belgium Energy Costs → Configure → 🔢 Update Gas Meter Reading

**Via service call** (for automations):
```yaml
service: belgium_energy_costs.update_gas_reading
data:
  reading: 13500.5
```

## Updating Annual Costs

When your new ENGIE contract arrives (typically each June):

Settings → Devices & Services → Belgium Energy Costs → Configure → ⚡ Update Electricity Costs *or* 🔥 Update Gas Costs

Sensors update immediately — no restart required.

## Example Dashboard Card (Energy tab)

```yaml
- type: entities
  title: ⚡ Electricity
  entities:
    - entity: sensor.total_electricity_cost_peak
      name: "Current Rate – Peak"
    - entity: sensor.total_electricity_cost_off_peak
      name: "Current Rate – Off-Peak"
    - entity: sensor.electricity_total_cost_since_contract_start
      name: "Total Cost"
    - entity: sensor.electricity_estimated_annual_cost
      name: "Estimated Annual Cost"

- type: entities
  title: 🔥 Gas
  entities:
    - entity: sensor.total_gas_cost
      name: "Current Rate"
    - entity: sensor.gas_total_cost_since_contract_start
      name: "Total Cost"
    - entity: sensor.gas_estimated_annual_cost
      name: "Estimated Annual Cost"

- type: entities
  title: 💰 Combined
  entities:
    - entity: sensor.total_energy_cost_since_contract_start
      name: "Total Energy Bill"
    - entity: sensor.total_estimated_annual_energy_cost
      name: "Estimated Annual Total"
```

## Architecture Notes

- **Event-driven**: sensors subscribe to P1 meter and ENGIE price changes via `async_track_state_change_event` — no polling
- **Debounced**: a shared `_UpdateThrottle` per config entry deduplicates subscriptions and batches state writes (5 s window) to reduce event-loop pressure from high-frequency P1 updates
- **Direct object references**: derived sensors hold Python references to their dependencies and call `.native_value` directly — no `hass.states.get()` round-trips on sibling sensors
- **Entry-scoped unique IDs**: all entity unique IDs include the config entry ID, so multiple installations never collide

## Dependencies

- [hass-engie-be](https://github.com/myTselection/hass-engie-be) by @myTselection

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — especially if you're in Flanders or Wallonia and want to help verify regional cost structures.

## Support

- [GitHub Issues](https://github.com/ddebaets/belgium-energy-costs/issues)
- [Home Assistant Community Forum](https://community.home-assistant.io/)

## License

MIT License — see [LICENSE](LICENSE)
