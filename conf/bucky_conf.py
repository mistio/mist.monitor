"""This files configures bucky"""

# Standard debug and log level
#debug = False
log_level = "INFO"  # DEBUG adds a considerable ammount of load
log_fmt = "%(asctime)s [%(levelname)s] %(module)s - %(message)s"

# Whether to print the entire stack trace for errors encountered
# when loading the config file
full_trace = True

metricsd_enabled = False
statsd_enabled = False

###### COLLECTD ######
# Basic collectd configuration
collectd_ip = "0.0.0.0"
collectd_port = 25826
collectd_enabled = True

collectd_auth_file = "/home/mist/mist.monitor/conf/collectd.passwd"
collectd_security_level = 2  # 0: None, 1: Sign, 2: Encrypt

# A list of file names for collectd types.db
# files.
collectd_types = ["conf/types.db"]

# A mapping of plugin names to converter callables. These are
# explained in more detail in the README.
from mist.bucky_extras.collectd_converters import PingConverter
from mist.bucky_extras.collectd_converters import MistPythonConverter
collectd_converters = {
    'ping': PingConverter(),
    'mist.python': MistPythonConverter(),
}

# Whether to load converters from entry points. The entry point
# used to define converters is 'bucky.collectd.converters'.
## collectd_use_entry_points = True

###### GRAPHITE ######
# Basic Graphite configuration
graphite_ip = "127.0.0.1"
graphite_port = 2014

# If the Graphite connection fails these numbers define how it
# will reconnect. The max reconnects applies each time a
# disconnect is encountered and the reconnect delay is the time
# in seconds between connection attempts. Setting max reconnects
# to a negative number removes the limit.
#graphite_max_reconnects = 3
#graphite_reconnect_delay = 5

# Configuration for sending metrics to Graphite via the pickle
# interface. Be sure to edit graphite_port to match the settings
# on your Graphite cache/relay.
graphite_pickle_enabled = True
#graphite_pickle_buffer_size = 500

###### GENERAL SETTINGS ######
# Bucky provides these settings to allow the system wide
# configuration of how metric names are processed before
# sending to Graphite.
#
# Prefix and postfix allow to tag all values with some value.
name_prefix = "bucky"
name_postfix = None

# The replacement character is used to munge any '.' characters
# in name components because it is special to Graphite. Setting
# this to None will prevent this step.
name_replace_char = '_'

# Optionally strip duplicates in path components. For instance
# a.a.b.c.c.b would be rewritten as a.b.c.b
name_strip_duplicates = True

# Bucky reverses hostname components to improve the locality
# of metric values in Graphite. For instance, "node.company.tld"
# would be rewritten as "tld.company.node". This setting allows
# for the specification of hostname components that should
# be stripped from hostnames. For instance, if "company.tld"
# were specified, the previous example would end up as "node".
#name_host_trim = []

# Processor is a callable that takes a (host, name, val, time) tuple as input
# and is expected to return a tuple of the same structure to forward the sample
# to the clients, or None to drop it.
#def debug_proc(host, name, val, time):
#    print host, name, val, time
#    return host, name, val, time
#processor = debug_proc

from mist.bucky_extras.processors.timeprocessor import TimeConverterSingleThread
from mist.bucky_extras.processors.core_observer import NewMetricsObserver
from mist.bucky_extras.processors.composite import gen_composite_processor

processor = gen_composite_processor(
    TimeConverterSingleThread(13),
    NewMetricsObserver(path='conf/discovered_metrics.conf'),
)
