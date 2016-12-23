"""Parses user defined settings from settings.py in top level dir."""
import logging
import os
import ast
import etcd

log = logging.getLogger(__name__)


# Parse user defined settings from settings.py in the top level project dir
settings_file = os.getenv('MONITOR_SETTINGS_FILE') or 'settings.py'
settings = {}
try:
    execfile(settings_file, settings)
except IOError:
    log.warning("No %s file found." % settings_file)
except Exception as exc:
    log.error("Error parsing settings py: %r", exc)


CORE_URI = settings.get("CORE_URI",
                        os.environ.get("CORE_URI", "http://mist"))
GRAPHITE_URI = settings.get("GRAPHITE_URI",
                            os.environ.get("GRAPHITE_URI",
                                           "http://graphite"))
MONGO_URI = settings.get("MONGO_URI",
                         os.environ.get("MONGO_URI", "mongodb:27017"))
MEMCACHED_URI = settings.get("MEMCACHED_URI", ["memcached:11211"])
SSL_VERIFY = settings.get("SSL_VERIFY", False)
AUTH_FILE_PATH = settings.get(
    "AUTH_FILE_PATH",
    os.environ.get("AUTH_FILE_PATH", os.getcwd() + "/opt/mist/collectd.passwd")
)

# Defines timings of notifications sent to core from mist.alert when a rule
# is triggered. (When untriggered we always send a single notification right
# away.) This is the default reminder list used if one isn't specified from
# core when rule is created/updated.
REMINDER_LIST = settings.get(
    "REMINDER_LIST",
    [
        0,  # notification level 0 - right away
        60 * 10,  # notification level 1 - 10 mins
        60 * 60,  # notification level 2 - 1 hour
        60 * 60 * 24,  # notification level 3 - 1 day
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
