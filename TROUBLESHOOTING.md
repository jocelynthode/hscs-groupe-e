# Troubleshooting

## Integration doesn't appear after HACS install

1. Check that the files exist at `/config/custom_components/groupe_e/`.
2. Go to **Settings** > **System** > **Logs** and search for `groupe_e` or `custom_components`.
3. Common causes:
   - **Manifest error**: ensure HACS category was set to **Integration** (not Plugin/Theme).
   - **HACS failed to download**: check HACS logs for `Validation failed` or `Could not download`.

## No data in Energy Dashboard

1. Add `custom_components.groupe_e: debug` to your logger config and restart.
2. Check logs for:
   - `"Adding N entries for ..."`, data was fetched and inserted.
   - `UpdateFailed`, an error occurred during fetch.
3. In **Settings** > **Energy**, click **Add Grid Consumption** and select **Groupe-E Grid Energy**. If the source doesn't appear, no statistics have been recorded yet.

## After upgrading to v2.1.0

- **"Cannot migrate unique_id ... already in use" warning**: you re-added the same premise under the new version before the old entry was migrated. The old entry keeps its identity and still works; delete whichever duplicate you don't want.
- **"missing NT/HT tariff prices" warning**: your entry lost its prices to a v2.0.0 reconfigure bug. Set both prices under **Configure** (options) — until then, cost statistics are computed at 0 CHF/kWh. Existing cost statistics inserted while prices were missing can be corrected with `groupe_e.reset_statistics` (optionally with `rebuild_since`).
- Migration runs automatically on restart; entities, history, and Energy Dashboard links are preserved.

## Daily totals differ slightly from Groupe-E's portal/app

If you compare the Energy Dashboard's daily consumption against the official Groupe-E daily figures, they differ by a small amount (typically ±0.1 kWh). This is expected and not a bug, no measurement is double-counted or lost.

**Why:** Groupe-E's quarter-hourly API delivers 96 points per day, timestamped 00:15 through 24:00. The point at 24:00 (midnight) is the reading for the quarter 00:00–00:15, but Groupe-E's own daily aggregate counts it as part of the day that is _ending_. The integration instead buckets measurements by their hour start, so the midnight point lands in the first hour of the _following_ day.

Concretely, for a day where the midnight reading is 0.6 kW (0.15 kWh):

- Groupe-E daily total: points 00:15–24:00 of that day (midnight point included)
- Integration daily total: previous day's midnight point + points 00:15–23:45

The difference between the two is always `(midnight reading of this day) − (midnight reading of the next day)`, oscillates around zero, and never accumulates. The cumulative (`sum`) statistics remain exact.

## Authentication errors

- **Wrong credentials**: use **Reconfigure** (three-dot menu on the integration) to update username/password.
- **Persistent 401**: your account may have been locked or the portal password changed. Verify you can log in at [my.groupe-e.ch](https://my.groupe-e.ch).
- **Login rate limit**: the API may temporarily block repeated failed login attempts. Wait a few minutes before retrying.
