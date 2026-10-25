"""Constants for the Salzburg Netz smart meter integration."""

DOMAIN = "salzburgnetz"

API_BASE = "https://api.salzburgnetz.at/api/v1"

CONF_API_KEY = "api_key"
CONF_GPNR = "gpnr"
CONF_ZP = "zp"
# Optional: a sensor with the price per kWh (e.g. from a bookkeeping app). Its
# `valid_from` attribute, if present, says from which day that price applies.
CONF_PRICE_ENTITY = "price_entity"

# Data is refreshed once a day and mostly complete by 10-12h (per Salzburg Netz).
SYNC_HOUR = 11
SYNC_MINUTE = 40

# Days re-fetched every day, so late or corrected values get picked up.
RECENT_DAYS = 3
# Long ranges time out at the gateway; 90 days per request works.
CHUNK_DAYS = 90
# The API serves at most three years of load profile data.
HISTORY_DAYS = 3 * 365
# Older 90-day pieces fetched per day while backfilling (the API allows only a
# handful of requests per day, shared with anything else using the same account).
BACKFILL_CHUNKS_PER_DAY = 1

OBIS_CONSUMPTION = "1-1:1.9.0"
OBIS_FEED_IN = "1-1:2.9.0"

SIGNAL_UPDATED = f"{DOMAIN}_updated_{{}}"
