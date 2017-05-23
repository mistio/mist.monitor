"""This file configures bucky"""
log_level = "INFO"  # DEBUG adds a considerable ammount of load
log_fmt = "%(asctime)s [%(levelname)s] %(module)s - %(message)s"
full_trace = True
metricsd_enabled = False
statsd_enabled = False
collectd_ip = "0.0.0.0"
collectd_port = 25826
collectd_enabled = True
collectd_counter_eq_derive = True
collectd_workers = 4
collectd_auth_file = "/opt/mist/collectd.passwd"
collectd_security_level = 1  # 0: None, 1: Sign, 2: Encrypt
collectd_types = ["/mist.monitor/conf/types.db",
                  "/mist.monitor/conf/types-perfwatcher.db"]
from mist.bucky_extras.collectd_converters import PingConverter
from mist.bucky_extras.collectd_converters import MistPythonConverter
collectd_converters = {
    'ping': PingConverter(),
    'mist.python': MistPythonConverter(),
}
graphite_ip = "graphite"
graphite_port = 2004  # 2004 is pickle protocol, 2003 plaintext protocol
graphite_pickle_enabled = True
name_prefix = "bucky"
name_postfix = None
name_replace_char = '_'
name_strip_duplicates = True
from mist.bucky_extras.processors.timeprocessor import TimeConverterSingleThread
from mist.bucky_extras.processors.core_observer import NewMetricsObserver
from mist.bucky_extras.processors.composite import gen_composite_processor
processor = gen_composite_processor(
    TimeConverterSingleThread(13),
    NewMetricsObserver(path='/mist.monitor/conf/discovered_metrics.conf'),
)
