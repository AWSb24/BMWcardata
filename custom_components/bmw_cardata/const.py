"""Constants for BMW CarData integration."""

DOMAIN = "bmw_cardata"

# BMW OAuth2
BMW_DEVICE_CODE_URL = "https://customer.bmwgroup.com/gcdm/oauth/device/code"
BMW_TOKEN_URL = "https://customer.bmwgroup.com/gcdm/oauth/token"
BMW_SCOPES = "authenticate_user openid cardata:streaming:read"

# BMW CarData REST API
BMW_API_BASE = "https://customer.bmwgroup.com"
# Scope needed for the REST API in addition to streaming.
BMW_SCOPE_API = "cardata:api:read"
BMW_SCOPE_STREAMING = "cardata:streaming:read"

# Operating modes (which data source(s) to use)
MODE_MQTT = "mqtt"
MODE_API = "api"
MODE_MIXED = "mixed"
DEFAULT_MODE = MODE_MQTT

# REST API polling. The API is limited to 50 requests / 24h (error CU-429),
# so the interval is deliberately conservative and floored.
API_POLL_DEFAULT_MINUTES = 60
API_POLL_MIN_MINUTES = 30

# BMW MQTT broker
BMW_MQTT_HOST = "customer.streaming-cardata.bmwgroup.com"
BMW_MQTT_PORT = 9000
BMW_MQTT_KEEPALIVE = 30


def scopes_for_mode(mode: str) -> str:
    """Return the OAuth scope string to request for the chosen mode."""
    parts = ["authenticate_user", "openid"]
    if mode in (MODE_API, MODE_MIXED):
        parts.append(BMW_SCOPE_API)
    if mode in (MODE_MQTT, MODE_MIXED):
        parts.append(BMW_SCOPE_STREAMING)
    return " ".join(parts)

# Token refresh
SOFT_REFRESH_MARGIN_SECONDS = 10 * 60  # refresh 10 min before exp
HARD_REFRESH_INTERVAL_SECONDS = 45 * 60  # refresh at least every 45 min
CLOCK_SKEW_SECONDS = 60

# Config keys
CONF_CLIENT_ID = "client_id"
CONF_GCID = "gcid"
CONF_VIN = "vin"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ID_TOKEN = "id_token"
CONF_TOKEN_EXPIRES = "token_expires"
CONF_MODE = "mode"
CONF_API_POLL_INTERVAL = "api_poll_interval"  # minutes
CONF_CONTAINER_ID = "container_id"

# Data keys for known entity types
ATTR_VIN = "vin"
ATTR_VALUE = "value"
ATTR_UNIT = "unit"
ATTR_TIMESTAMP = "timestamp"
ATTR_DATA = "data"

# Topic pattern from BMW: GCID/VIN/eventName
CONNECTION_STATUS = "connection_status"

# Dispatcher signals (used by __init__, sensor, binary_sensor)
SIGNAL_CARDATA_UPDATE = "bmw_cardata_update"
SIGNAL_CONNECTION_CHANGED = "bmw_cardata_connection_changed"


def get_device_name(gcid: str, vin: str | None) -> str:
    """Build device name from VIN and GCID (config flow always provides both)."""
    gcid = (gcid or "").strip()
    vin = (vin or "").strip()
    if vin and gcid:
        return f"BMW {vin} / {gcid}"
    if gcid:
        return f"BMW {gcid}"
    return "BMW CarData"
