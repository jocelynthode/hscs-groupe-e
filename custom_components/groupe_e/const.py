"""Constants for the Groupe-E Energy integration."""

DOMAIN = "groupe_e"

OAUTH2_AUTHORIZE = (
    "https://login.my.groupe-e.ch/realms/my-groupe-e/protocol/openid-connect/auth"
)
OAUTH2_TOKEN = (
    "https://login.my.groupe-e.ch/realms/my-groupe-e/protocol/openid-connect/token"
)

API_BASE_URL = "https://my.groupe-e.ch/api"
SMARTMETER_DATA_URL = f"{API_BASE_URL}/smartmeter-data"
USERINFO_URL = (
    "https://login.my.groupe-e.ch/realms/my-groupe-e/protocol/openid-connect/userinfo"
)

CONF_PREMISE = "premise"
CONF_PARTNER = "partner"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_STAT_ID_DISCRIMINATOR = "stat_id_discriminator"
CONF_TARIFF_SCHEDULE = "tariff_schedule"
CONF_NT_PRICE = "nt_price"
CONF_HT_PRICE = "ht_price"

DEFAULT_UPDATE_INTERVAL = 12  # hours
DEFAULT_TARIFF_SCHEDULE = [{"start": 7, "end": 12}, {"start": 17, "end": 23}]
TARIFF_TIMEZONE = "Europe/Zurich"

CURRENCY = "CHF"
ENERGY_PRICE_UNIT = "CHF/kWh"
