"""Constants for BMW CarData integration."""

DOMAIN = "bmw_cardata"

# BMW OAuth2
BMW_DEVICE_CODE_URL = "https://customer.bmwgroup.com/gcdm/oauth/device/code"
BMW_TOKEN_URL = "https://customer.bmwgroup.com/gcdm/oauth/token"
BMW_SCOPES = "authenticate_user openid cardata:streaming:read"

# BMW MQTT broker
BMW_MQTT_HOST = "customer.streaming-cardata.bmwgroup.com"
BMW_MQTT_PORT = 9000
BMW_MQTT_KEEPALIVE = 30

# Token refresh
SOFT_REFRESH_MARGIN_SECONDS = 10 * 60  # refresh 10 min before exp
HARD_REFRESH_INTERVAL_SECONDS = 45 * 60  # refresh at least every 45 min
CLOCK_SKEW_SECONDS = 60

# Config keys
CONF_CLIENT_ID = "client_id"
CONF_GCID = "gcid"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ID_TOKEN = "id_token"
CONF_TOKEN_EXPIRES = "token_expires"

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
