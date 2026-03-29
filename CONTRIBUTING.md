# Contributing to Belgium Energy Costs

Thank you for considering contributing to this project! 🎉

## How to Contribute

### Adding Regional Support

We need help supporting all Belgian regions! If you live in **Flanders** or **Wallonia**:

1. **Open an Issue**
   - Go to [Issues](https://github.com/ddebaets/belgium-energy-costs/issues/new)
   - Title: "Regional Support: [Your Region]"
   - Include your ENGIE contract pages:
     - Pages 21-22 for electricity costs
     - Pages 25-26 for gas costs
   - Mention your grid operator (Fluvius, ORES, RESA, AIEG, AIESH)
   - Share your gas conversion factor (usually on page 26)

2. **We'll Verify and Add**
   - We'll verify the cost structure matches the region
   - Add verified defaults to the integration
   - Update the region as "Fully Supported"
   - Credit you in the release notes!

### Reporting Bugs

Found a bug? Please:

1. Check [existing issues](https://github.com/ddebaets/belgium-energy-costs/issues) first
2. If new, create an issue with:
   - Clear description of the problem
   - Steps to reproduce
   - Expected vs actual behavior
   - Home Assistant version
   - Integration version
   - Relevant logs (if applicable)

### Feature Requests

Have an idea? We'd love to hear it!

1. Check if it's [already requested](https://github.com/ddebaets/belgium-energy-costs/issues)
2. Open a new issue with:
   - Clear description of the feature
   - Use case / why it would be valuable
   - How you envision it working

### Code Contributions

Want to contribute code?

1. **Fork the repository**
2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes**
   - Follow existing code style
   - Add comments where helpful
   - Test thoroughly
4. **Submit a Pull Request**
   - Clear description of changes
   - Reference any related issues
   - Screenshots/examples if UI changes

## Development Setup

1. Clone the repository
2. Place in `/config/custom_components/belgium_energy_costs/`
3. Restart Home Assistant
4. Enable debug logging in `configuration.yaml`:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.belgium_energy_costs: debug
   ```

## Code Style

- Follow Home Assistant's [development guidelines](https://developers.home-assistant.io/)
- Use type hints
- Add docstrings to classes and methods
- Keep functions focused and readable

## Testing

Before submitting:

- [ ] Integration loads without errors
- [ ] Config flow completes successfully
- [ ] All sensors appear and update correctly
- [ ] Options flow works (if modified)
- [ ] No errors in Home Assistant logs

## Questions?

Feel free to:
- Open an issue for discussion
- Ask in the Home Assistant Community Forum
- Reach out via GitHub

## Code of Conduct

Be respectful, inclusive, and constructive. We're all here to make great software together! 🚀

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
