# Testing the Groupe-E Integration

This document explains how to test the integration to ensure it is working correctly.

## 1. Local Testing with a Sandbox/Dev Instance

To test this integration, you should have a Home Assistant development environment or a separate "test" instance.

### Step-by-Step Testing

1. **Deploy to custom_components**:
   Copy the `custom_components/groupe_e` directory to your Home Assistant `config/custom_components` folder.
2. **Check Logs**:
   Restart Home Assistant and monitor the logs (`home-assistant.log`). You should see no errors related to the `groupe_e` component during startup.
3. **Verify OAuth2 Flow**:
   Go to **Settings** > **Devices & Services** > **Add Integration**. Search for "Groupe-E Energy".
   - Ensure the external login page (Keycloak) opens correctly.
   - Verify that after signing in, you are redirected back to Home Assistant and the "Success" message appears.
4. **Sensor Verification**:
   - Go to **Developer Tools** > **States**.
   - Search for `sensor.groupe_e_energy_consumption`.
   - Check if the state (value in kWh) is being populated.
5. **Energy Dashboard**:
   - Go to **Settings** > **Dashboards** > **Energy**.
   - Try to add the `Groupe-E Energy Consumption` sensor to the "Grid consumption" section. It should appear in the list.

## 2. API Verification (Manual)

If you want to verify if the API client is working correctly without the full HA setup, you can use a Python script with a temporary token (extracted from your browser during a manual session):

```python
import asyncio
from aiohttp import ClientSession
from datetime import datetime, timedelta
from custom_components.groupe_e.api import GroupeEAPI

async def test_api():
    token = "YOUR_TEMP_TOKEN_HERE"
    async with ClientSession() as session:
        api = GroupeEAPI(session, token)

        # Test User Info
        user_info = await api.get_user_info()
        print(f"User Info: {user_info}")

        # Test Smart Meter Data
        premise = "106180" # Replace with yours
        partner = "6050184" # Replace with yours
        end = datetime.now()
        start = end - timedelta(days=1)

        data = await api.get_smartmeter_data(premise, partner, start, end)
        print(f"Smart Meter Data: {data}")

if __name__ == "__main__":
    asyncio.run(test_api())
```

## 3. Debugging

To get more information about what the integration is doing, add the following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.groupe_e: debug
```

Check the logs for:

- "Fetching smartmeter data" messages.
- JSON responses from the API (be careful, as these might contain PII).
- Any `UpdateFailed` errors.

## 4. Run Tests

```bash
pip install -r requirements_test.txt
python -m pytest tests/ -v
```
