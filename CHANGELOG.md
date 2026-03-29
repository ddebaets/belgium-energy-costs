# Changelog

All notable changes to the Belgium Energy Costs integration will be documented in this file.

## [5.2.0] - 2026-03-29

### Fixed
- Total estimated annual energy cost sensor now correctly aggregates electricity and gas annual costs
- Gas conversion factor field UI no longer shows slider (text input only)
- Removed duplicate sensor creation bug from legacy setup function

### Changed
- Gas average monthly consumption now displays in kWh/month instead of m³/month for consistency

## [5.1.0] - 2026-03-29

### Added
- Gas consumption sensors (m³ and kWh variants)
- Monthly average consumption sensors for electricity and gas
- Monthly average cost sensors for electricity, gas, and combined total
- Total average monthly energy cost sensor

### Fixed
- All UI sliders removed from config flow (cost fields, gas conversion, baselines)
- Duplicate sensor creation eliminated

## [5.0.0] - 2026-03-29

### Changed
- Complete sensor architecture with 40+ sensors
- Enhanced gas tracking with consumption and cost breakdown
- Improved monthly and annual projections

## [4.3.0] - 2026-03-29

### Fixed
- Baseline number input fields now accept whole numbers correctly (fixed division by 1000 bug)
- Peak, off-peak, and gas baseline values now stored and displayed correctly

## [4.0.0] - 2026-03-29

### Added
- Auto-created gas meter number entity (`number.belgium_energy_costs_gas_meter_reading`)
- Service for gas meter updates (`belgium_energy_costs.update_gas_reading`)
- Options flow for updating costs and gas readings without restart

### Changed
- Gas meter no longer requires manual `input_number` helper creation
- Integration now manages gas meter entity automatically

## [3.0.0] - 2026-03-29

### Added
- Full UI configuration flow (8-step wizard)
- Regional support framework (Brussels, Flanders, Wallonia)
- Config flow validation for required ENGIE sensors

### Changed
- Moved from YAML-only to config flow UI setup
- Improved user experience for annual cost updates

## [2.0.0] - 2026-03-29

### Added
- Initial config flow implementation
- Basic UI setup support

## [1.0.0] - 2026-03-29

### Added
- Initial release
- YAML configuration support
- Brussels (SIBELGA) full support
- Electricity tracking (bi-horaire and single tariff)
- Gas tracking with manual meter updates
- Solar export support
- Integration with hass-engie-be for variable prices
- Energy Dashboard compatibility
