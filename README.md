# Groupe-E Energy for Home Assistant

This Home Assistant integration fetches quarter-hourly consumption data from Groupe-E (Switzerland), splits it by tariff (Normal/High), calculates the historical energy cost, and inserts everything directly into Home Assistant's long-term statistics for use by the **Energy Dashboard** — no YAML, no template sensors, no automations required.

> **Note:** Groupe-E data has a 1-day lag: today's consumption is only available tomorrow. The integration handles this transparently by always requesting from the last known point.

## Features

- **Direct Login**: Secure login using your official Groupe-E email and password.
- **Energy Dashboard Ready**: Inserts 15-minute kWh data as three energy statistics (Normal Tariff, High Tariff, Grid Total) plus a **cumulative cost statistic** — automatically calculated using your contract's NT/HT prices.
- **Configurable Tariff Schedule**: Set your high-tariff periods (e.g. `07:00-12:00,17:00-23:00`) in the integration options. Defaults to Swiss standard hours.
- **Configurable Pricing**: Enter your NT and HT prices (CHF/kWh) from your Groupe-E contract during setup.
- **Automatic Cost Calculation**: At every data fetch, the integration calculates the historical cost per hour using the tariff that was active at that time — no need for a "current price" entity.
- **Automatic Timezone Handling**: Tariff periods are evaluated in Swiss local time (`Europe/Zurich`), with correct DST transitions.
- **Configurable Polling**: Adjust how often data is fetched (default: every 12 hours).
- **Historical Backfill**: On first run, fetches data from January 1st of the current year — calculates both energy and cost for all of it.
- **Multi-meter support**: Each premise gets isolated statistic IDs; a custom discriminator can be set if needed.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant.
2. Click on **Integrations**.
3. Click the three dots in the top right corner and select **Custom repositories**.
4. Paste the URL of this repository: `https://github.com/carnevlu/hscs-groupe-e`
5. Select **Integration** as the category.
6. Click **Add** and then install the **Groupe-E Energy** integration.
7. Restart Home Assistant.

## Configuration

1. In Home Assistant, go to **Settings** > **Devices & Services**.
2. Click **Add Integration** and search for **Groupe-E Energy**.
3. Enter the following information:
   - **Username**: Your Groupe-E email.
   - **Password**: Your Groupe-E password.
   - **Premise ID** (e.g. 106180): Your location identifier (see below).
   - **Partner ID** (e.g. 6050184): Your customer identifier (see below).
   - **Normal tariff price (CHF/kWh)**: Your normal-tariff (bas tarif) price per kWh.
   - **High tariff price (CHF/kWh)**: Your high-tariff (haut tarif) price per kWh.
   - **Statistics discriminator** (optional, defaults to premise): A label for your meter. Useful if you have multiple premises, each gets its own statistics series (e.g. `groupe_e:energy_consumption_main_house`).

### How to find your Premise and Partner ID

To obtain your specific IDs, you need to inspect the network traffic on the official portal:

1. Log in to [my.groupe-e.ch](https://my.groupe-e.ch).
2. Go to the page where you can see your daily consumption graphs.
3. Press `F12` to open the **Developer Tools** and go to the **Network** tab.
4. Refresh the page or click on a different date to trigger a data reload.
5. In the "Filter" box, type `smartmeter-data`.
6. Click on the request and look at the **Payload** (or Request Body). You will see a JSON like this:
   ```json
   {
     "premise": "106180",
     "partner": "6050184",
     ...
   }
   ```
7. Use these values in the Home Assistant setup form.

## Options

After configuration, go to **Settings** > **Devices & Services**, click the three-dot menu on the Groupe-E integration, and select **Configure**:

| Setting                 | Description                                                                                                                      |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **NT price**            | Your normal-tariff (bas tarif) price in CHF/kWh. Required.                                                                       |
| **HT price**            | Your high-tariff (haut tarif) price in CHF/kWh. Required.                                                                        |
| **Update interval**     | How often to fetch new data (minimum 1 hour, default 12 hours).                                                                  |
| **High tariff periods** | Comma-separated time ranges in Swiss local time, e.g. `07:00-12:00,17:00-23:00`. Defaults to Swiss standard hours if left empty. |

> Prices vary per contract and change annually. Update them via **Configure** when your tariff changes.

## Sensors

| Sensor                               | Description                                        | Unit    |
| ------------------------------------ | -------------------------------------------------- | ------- |
| `Groupe-E Normal Tariff Consumption` | Total kWh consumed during normal-tariff periods    | kWh     |
| `Groupe-E High Tariff Consumption`   | Total kWh consumed during high-tariff periods      | kWh     |
| `Groupe-E Grid Energy`               | Total kWh consumed (NT + HT)                       | kWh     |
| `Groupe-E Energy Cost`               | Cumulative variable electricity cost               | CHF     |
| `Groupe-E Electricity Price`         | Current active price per kWh (changes with tariff) | CHF/kWh |

## Usage in the Energy Dashboard

After configuration, go to **Settings** > **Energy**:

1. Under **Electricity consumption**, click **Add consumption**.
2. Select the **Groupe-E Grid Energy** statistic.
3. Under **Cost**, select the **Groupe-E Energy Cost** statistic.
4. The Energy Dashboard will display your consumption with the correct cost breakdown, reflecting the correct NT/HT pricing for every historical data point.

No template sensors, no automations, no per-tariff static prices to enter.

### Statistic IDs

- `groupe_e:energy_consumption_<premise>_normal_tariff` (kWh during normal-tariff hours)
- `groupe_e:energy_consumption_<premise>_high_tariff` (kWh during high-tariff hours)
- `groupe_e:energy_consumption_<premise>_total` (total kWh)
- `groupe_e:energy_consumption_<premise>_cost` (cumulative CHF)

## Services

### `groupe_e.reset_statistics`

Delete all Groupe-E statistics and re-fetch from the API.

| Field           | Type               | Description                                                                                          |
| --------------- | ------------------ | ---------------------------------------------------------------------------------------------------- |
| `entry_id`      | string (required)  | The Groupe-E config entry to reset                                                                   |
| `rebuild_since` | date (optional)    | ISO date (e.g. `2026-01-01`). Clears and rebuilds from this date onward, preserving data before it   |
| `clear_all`     | boolean (optional) | If `true`, deletes ALL statistics and rebuilds from Jan 1 of current year. Overrides `rebuild_since` |

If neither field is provided, preserves nothing before Jan 1 of the current year and rebuilds from that date.

## Troubleshooting

| Symptom                                                | Likely cause                                         | Fix                                                                                      |
| ------------------------------------------------------ | ---------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Sensors show "unknown" after startup                   | First refresh failed (e.g. HTTP 500)                 | Check logs. The integration will retry on next poll interval.                            |
| Sensors show "This entity is no longer being provided" | `async_setup_entry` failed                           | Restart HA. The integration now tolerates first-refresh failures.                        |
| No data in Energy Dashboard after reset                | Statistics need time to commit                       | Wait a few minutes, or trigger a manual refresh via the service.                         |
| Wrong cost in Energy Dashboard                         | Prices changed but data was inserted with old prices | Use `groupe_e.reset_statistics` with `rebuild_since` set to the date the prices changed. |

## How it works

1. The integration fetches 15-minute consumption data from the Groupe-E API.
2. It aggregates measurements into hourly kWh values.
3. Each hour is classified as NT or HT based on the configured tariff schedule and Swiss local time.
4. The hourly kWh is multiplied by the appropriate NT or HT price to calculate the cost.
5. All four statistic series (NT, HT, total energy, total cost) are inserted as **external statistics** with historical timestamps.
6. The Energy Dashboard uses these pre-calculated statistics — it never needs to know what tariff was active at any historical time.

## Security and Privacy

- **No Third-Party OAuth**: The integration communicates directly with Groupe-E's servers.
- **Storage**: Your credentials and IDs are stored securely in Home Assistant's internal configuration.
- **Update credentials**: Go to **Settings** > **Devices & Services**, click the three-dot menu on the Groupe-E integration, and select **Reconfigure**, no need to delete and re-add.

## Support

This is an unofficial integration. For issues related to the API or your Groupe-E account, please contact Groupe-E support. For issues with this integration, please open an issue on GitHub.
