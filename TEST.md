# Testing the Groupe-E Integration

## 1. Automated Tests

```bash
pip install -r requirements_test.txt
python -m pytest tests/ -v
```

The test suite covers:

- **API client**: login, token refresh, 401 retry, error handling
- **`_safe_float`**: int, float, None, numeric strings, non-numeric strings, bools
- **`_parse_timestamp_ms`**: valid ms timestamps, None, booleans, strings, missing keys
- **`measurements_to_statistics`**: empty input, single measurement, cumulative sums, duplicate skipping, invalid values/timestamps, existing sum continuation

These pure-function tests do not require HA fixtures or mocked recorder instances.

## 2. Integration Testing

1. **Deploy** the `custom_components/groupe_e` directory to your HA `config/custom_components`.
2. **Add the integration** via **Settings** > **Devices & Services** > **Add Integration** > **Groupe-E Energy**.
3. **Check logs** at `custom_components.groupe_e: debug` for fetch and statistics-insertion messages.
4. **Verify statistics**: Go to **Settings** > **Energy** and add the **Groupe-E Energy Consumption** source. The dashboard should show quarter-hourly data.

## 3. Debugging

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.groupe_e: debug
```

Look for:

- `"Updating sensor data"` / `"Adding N statistics entries"`, confirms data was fetched and inserted.
- `"Skipping measurement with invalid ..."`, API returned a bad value.
- `UpdateFailed` errors, credential or API issues.

## 4. API Verification

To test the API client independently:

```python
import asyncio
from aiohttp import ClientSession
from datetime import datetime, timedelta
from custom_components.groupe_e.api import GroupeEAPI


async def test_api():
    async with ClientSession() as session:
        api = GroupeEAPI(session, "your@email.com", "your_password")
        data = await api.get_smartmeter_data(
            "106180",
            "6050184",
            datetime.now() - timedelta(days=2),
            datetime.now(),
            resolution="quarter-hourly",
        )
        print(data)


asyncio.run(test_api())
```
