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
   - `"Adding N statistics entries"`, data was fetched and inserted.
   - `"Skipping measurement with invalid ..."`, API returned bad data for some intervals.
   - `UpdateFailed`, an error occurred during fetch.
3. In **Settings** > **Energy**, click **Add Grid Consumption** and select **Groupe-E Energy Consumption**. If the source doesn't appear, no statistics have been recorded yet.

## Authentication errors

- **Wrong credentials**: use **Reconfigure** (three-dot menu on the integration) to update username/password.
- **Persistent 401**: your account may have been locked or the portal password changed. Verify you can log in at [my.groupe-e.ch](https://my.groupe-e.ch).
- **Login rate limit**: the API may temporarily block repeated failed login attempts. Wait a few minutes before retrying.
