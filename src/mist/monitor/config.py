"""Parses user defined settings from settings.py in top level dir."""

import logging
import os
import etcd

log = logging.getLogger(__name__)


# Parse user defined settings from settings.py in the top level project dir
settings = {}
try:
    execfile("settings.py", settings)
except IOError:
    log.warning("No settings.py file found.")
except Exception as exc:
    log.error("Error parsing settings py: %r", exc)

ETCD_BACKEND = os.getenv('ETCD_BACKEND') or settings.get('ETCD_BACKEND')

def get_default_gateway_ip():
    with open("/proc/net/route") as fh:
        for line in fh:
            fields = line.strip().split()
            if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                continue

            return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))

def etcd_get(client, key, default_value, type='string'):
    try:
        key = client.read('/mist/settings/%s' % key).value
        if type is 'string':
            key = str(key)
        elif type is 'integer':
            key = int(key)
        elif type is 'boolean':
            key = ast.literal_eval(key)
        elif type is 'list':
            key = [key]
    except etcd.EtcdKeyNotFound:
        key = default_value

    return key

if ETCD_BACKEND:
    if ETCD_BACKEND in ["gce", "gke", "GKE", "GCE"]:
        ETCD_URI = "etcd.default.svc.cluster.local"
    else:
        ETCD_URI = get_default_gateway_ip()
    try:
        client = etcd.Client(ETCD_URI, port=2379)
        machines = client.machines
        ETCD_EXISTS = True
    except:
        ETCD_EXISTS = False
        pass
else:
    ETCD_EXISTS = False

if ETCD_EXISTS:
    CORE_URI = etcd_get(client, 'CORE_URI', "http://localhost:8000")
    GRAPHITE_URI = etcd_get(client, 'GRAPHITE_URI', "http://graphite.default.svc.cluster.local")
    MONGO_URI = etcd_get(client, 'MONGO_URI', "mongodb.default.svc.cluster.local:27017")
    MEMCACHED_URI = etcd_get(client, 'MEMCACHED_URI', ["memcached.default.svc.cluster.local:11211"], type='list')
    SSL_VERIFY = etcd_get(client, 'SSL_VERIFY', False, type='boolean')
    AUTH_FILE_PATH = etcd_get(client, 'AUTH_FILE_PATH', "/opt/mist/collectd.passwd")
else:
    CORE_URI = settings.get("CORE_URI", "https://mist.io")
    GRAPHITE_URI = settings.get("GRAPHITE_URI", "http://localhost")
    MONGO_URI = settings.get("MONGO_URI", "localhost:27022")
    MEMCACHED_URI = settings.get("MEMCACHED_URI", ["localhost:11211"])
    SSL_VERIFY = settings.get("SSL_VERIFY", True)
    AUTH_FILE_PATH = settings.get("AUTH_FILE_PATH", os.getcwd() + "/conf/collectd.passwd")

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
