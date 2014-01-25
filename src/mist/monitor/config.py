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

RESET_KEY = settings.get("RESET_KEY", "")
