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

DEFAULT_UPDATE_INTERVAL = 60  # minutes
