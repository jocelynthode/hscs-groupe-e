# Groupe-E Energy for Home Assistant

This Home Assistant integration **does not create entities**. It fetches quarter-hourly consumption data from Groupe-E (Switzerland) and inserts it directly into Home Assistant's long-term statistics for use by the **Energy Dashboard**.

> **Note:** Groupe-E data has a 1-day lag: today's consumption is only available tomorrow. The integration handles this transparently by always requesting from the last known point.

## Features

- **Direct Login**: Secure login using your official Groupe-E email and password.
- **Energy Dashboard Ready**: Inserts 15-minute kWh data as two separate tariff statistics (Normal Tariff / High Tariff), each configurable with its own per-kWh price in the Energy Dashboard.
- **Configurable Tariff Schedule**: Set your high-tariff periods (e.g. `07:00-12:00,17:00-23:00`) in the integration options. Defaults to Swiss standard hours.
- **Automatic Timezone Handling**: Tariff periods are evaluated in Swiss local time (`Europe/Zurich`), with correct DST transitions.
- **Configurable Polling**: Adjust how often data is fetched (default: every 60 minutes).
- **Historical Backfill**: On first run, fetches the last 365 days of data. Missing tariff stats trigger a full backfill.
- **Overlapping fetch window**: Catches late API data corrections.
- **Multi-meter support**: Each premise gets an isolated statistic ID; a custom discriminator can be set if needed.

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
   - **Premise ID**: Your location identifier (see below).
   - **Partner ID**: Your customer identifier (see below).
   - **Statistics discriminator** (optional): A label for your meter (defaults to the premise ID). Useful if you have multiple premises, each gets its own statistics series (e.g. `groupe_e:energy_consumption_main_house`).

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

| Setting                 | Description                                                                                                                              |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Update interval**     | How often to fetch new data (minimum 15 minutes, default 60).                                                                            |
| **High tariff periods** | Comma-separated time ranges in Swiss local time, e.g. `07:00-12:00,17:00-23:00`. Defaults to Swiss standard hours if left empty. |

## Usage in the Energy Dashboard

After configuration, go to **Settings** > **Energy**:

1. Under **Electricity consumption**, click **Add consumption**.
2. Select the **Groupe-E Normal Tariff** statistic and enter the per-kWh price for normal-tariff electricity.
3. Click **Add consumption** again and select the **Groupe-E High Tariff** statistic with its per-kWh price.
4. The Energy Dashboard will display your consumption with the correct cost breakdown at full 15-minute granularity.

### Statistic IDs

- `groupe_e:energy_consumption_<premise>_normal_tariff` (kWh during normal-tariff hours)
- `groupe_e:energy_consumption_<premise>_high_tariff` (kWh during high-tariff hours)

## Security and Privacy

- **No Third-Party OAuth**: The integration communicates directly with Groupe-E's servers.
- **Storage**: Your credentials and IDs are stored securely in Home Assistant's internal configuration.
- **Update credentials**: Go to **Settings** > **Devices & Services**, click the three-dot menu on the Groupe-E integration, and select **Reconfigure**, no need to delete and re-add.

## Support

This is an unofficial integration. For issues related to the API or your Groupe-E account, please contact Groupe-E support. For issues with this integration, please open an issue on GitHub.
