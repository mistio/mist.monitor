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


CORE_URI = settings.get("CORE_URI", "https://mist.io")
# Almost all servers either run graphite locally or have a local graphite proxy
GRAPHITE_URI = settings.get("GRAPHITE_URI", "http://localhost")
MONGO_URI = settings.get("MONGO_URI", "localhost:27017")
MEMCACHED_URI = settings.get("MEMCACHED_URI", ["localhost:11211"])


# Verify core's SSL certificate when communicating via HTTPS
# (used by mist.alert when notifying core about rule status)
SSL_VERIFY = settings.get("SSL_VERIFY", True)


# Defines timings of notifications sent to core from mist.alert when a rule
# is triggered. (When untriggered we always send a single notification right
# away.) This is the default reminder list used if one isn't specified from
# core when rule is created/updated.
REMINDER_LIST = settings.get(
    "REMINDER_LIST",
    [
        0,  # notification level 0 - right away
        60,  # notification level 1 - 1 min
        60 * 5,  # notification level 2 - 5 mins
        60 * 10,  # notification level 3 - 10 mins
        60 * 30,  # notification level 4 - 30 mins
        60 * 60,  # notification level 5 - 1 hour
        60 * 60 * 2,  # notification level 6 - 2 hours
        60 * 60 * 6,  # notification level 7 - 6 hours
        60 * 60 * 10,  # notification level 8 - 10 hours
        60 * 60 * 20,  # notification level 9 - 20 hours
        60 * 60 * 24,  # notification level 10 - 1 day
    ]
)


# mist.alert periodically checks if the rules are triggered. This option
# defines mist.alert's period between two consecutive runs (in seconds).
ALERT_PERIOD = settings.get("ALERT_PERIOD", 15)
ALERT_THREADS = settings.get("ALERT_THREADS", 32)


# Graphite's storage interval, needed because derivative metrics always return
# None as their first value and to deal with that we ask for one step
# earlier and then strip measurements that are before the asked 'start'.
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


# Reset key is used to reset monitor's data. It needs to be set to a non empty
# string and sent along with a reset http request from core. Under normal
# circumstances it should be left blank for security reasons.
RESET_KEY = settings.get("RESET_KEY", "")


# Switch graphs/alerts to bucky
GRAPHS_BUCKY = settings.get("GRAPHS_BUCKY", False)
ALERTS_BUCKY = settings.get("ALERTS_BUCKY", False)
