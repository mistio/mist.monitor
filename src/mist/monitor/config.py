"""Parses user defined settings from settings.py in top level dir."""

import logging

log = logging.getLogger(__name__)


# Parse user defined settings from settings.py in the top level project dir
settings = {}
try:
    execfile("settings.py", settings)
except IOError:
    log.warning("No settings.py file found.")
except Exception as exc:
    log.error("Error parsing settings py: %r", exc)

CORE_URI = settings.get("CORE_URI", "http://localhost:6543")
GRAPHITE_URI = settings.get("GRAPHITE_URI", "http://graphite.mist.io")
MEMCACHED_URI = settings.get("MEMCACHED_URI", ["localhost:11211"])
MONGO_URI = settings.get("MONGO_URI", "localhost:27022")

# Needed to know the step, to ask one more step to handle less values for derivatives
# 10 secs for the last day,
# 60 secs for the last week,
# 5 mins for the last month,
# 1 hour for the last year,
# 1 day for the last 5 years,
RETENTIONS = settings.get(
    "RETENTIONS",
    {
        60 * 60 * 24: 10,
        60 * 60 * 24 * 7: 60,
        60 * 60 * 24 * 30: 60 * 5,
        60 * 60 * 24 * 30 * 12: 60 * 60,
        60 * 60 * 24 * 30 * 12 * 5: 60 * 60 * 24
    }
)

RESET_KEY = settings.get("RESET_KEY", "")
