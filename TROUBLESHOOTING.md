# Troubleshooting HACS Installation

If the Groupe-E integration does not appear in Home Assistant after installing it via HACS, follow these steps to collect logs and find the cause.

## 1. Check if the files exist

Open the **Terminal** or **File Editor** in Home Assistant and check if this folder exists:
`/config/custom_components/groupe_e/`

- **If it doesn't exist**: HACS failed to download the repository.
- **If it exists but the integration doesn't show up**: There is an error in the code or manifest preventing Home Assistant from loading it.

## 2. Check Home Assistant Logs

1. Go to **Settings** > **System** > **Logs**.
2. Click on **Home Assistant Core** (or "Load Full Logs").
3. Use `Ctrl+F` (or `Cmd+F`) to search for:
   - `groupe_e`
   - `custom_components`
   - `hacs`

Look for errors like:

- `Manifest file is invalid`
- `Integration 'groupe_e' not found`
- `Error loading custom_components.groupe_e`

## 3. Check HACS Logs

HACS writes its own logs into the main Home Assistant log.

1. Go to **Settings** > **System** > **Logs**.
2. Filter for `hacs`.
3. Look for messages like `Validation of carnevlu/hscs-groupe-e failed` or `Could not download`.

## 4. Common Fixes

- **Manifest Error**: Ensure `manifest.json` is valid JSON (I have verified this).
- **Missing Requirements**: Ensure your Home Assistant has internet access to download `aiohttp` (it usually does).
- **HACS Category**: When adding the Custom Repository, ensure you select **Integration** as the category. If you selected "Plugin" or "Theme", it won't work.
