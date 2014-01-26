import abc
import logging
import requests

from mist.monitor import config
from mist.monitor.exceptions import GraphiteError


MACHINE_PREFIX = "mist"
MIN_INTERVAL = 10

REQ_SESSION = None

log = logging.getLogger(__name__)


class GraphiteSeries(object):
    """Base graphite target class that defines an interface and provides
    convinience methods for subclasses to use."""

    __metaclass__ = abc.ABCMeta

    def __init__(self, uuid):
        self.uuid = uuid

    @property
    def head(self):
        return "%s-%s" % (MACHINE_PREFIX, self.uuid)

    @abc.abstractmethod
    def get_targets(self):
        """Return list of target strings."""
        return []

    def get_series(self, start=0, stop=0):
        """Get time series from graphite."""
        uri = self._construct_graphite_uri(self.get_targets(), start, stop)
        data = self._graphite_request(uri)
        return self._post_process_series(data)

    def _post_process_series(self, data):
        """Change to (timestamp, value) pairs and strip null."""

        new_data = {}
        for item in data:
            target = item['target']
            new_data[target] = [(timestamp, value)
                                for value, timestamp in item['datapoints']
                                if value is not None]
        return new_data

    def _construct_graphite_uri(self, targets, start, stop):
        targets_str = "&".join(["target=%s" % target for target in targets])
        uri = "%s/render?%s&format=json" % (config.GRAPHITE_URI, targets_str)
        start = int(start)
        stop = int(stop)
        if start:
            uri += "&from=%s" % start
        if stop:
            uri += "&until=%s" % stop
        return uri

    def _graphite_request(self, uri, use_session=False):
        """Issue a request to graphite."""

        global REQ_SESSION

        if use_session:
            log.debug("Using turbo http session")
            REQ_SESSION = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=100,
                                                    pool_maxsize=100)
            REQ_SESSION.mount('http://', adapter)
            REQ_SESSION.keep_alive = True
            req = REQ_SESSION
        else:
            req = requests

        try:
            log.info("Querying graphite uri: '%s'.", uri)
            resp = req.get(uri)
        except Exception as exc:
            log.error("Error sending request to graphite: %r", exc)
            raise GraphiteError(repr(exc))

        if resp.status_code != 200:
            log.error("Got error response from graphite: [%d] %s",
                      resp.status_code, resp.text)
            raise GraphiteError()

        return resp.json()


class SimpleGraphiteSeries(GraphiteSeries):

    alias = ""

    def __init__(self, uuid, alias=""):
        super(SimpleGraphiteSeries, self).__init__(uuid)
        if alias:
            self.alias = alias

    @abc.abstractmethod
    def get_inner_target(self):
        pass

    def get_targets(self):
        target = self.get_inner_target()
        if self.alias:
            target = "alias(%s,'%s')" % (target, self.alias)
        return [target]


class CombinedGraphiteSeries(GraphiteSeries):
    """Combines multiple GraphiteSeries instances together."""

    def __init__(self, uuid, series_list=None):
        """series should be a list of GraphiteSeries instances."""
        super(CombinedGraphiteSeries, self).__init__(uuid)
        for series in series_list:
            if not isinstance(series, GraphiteSeries):
                raise TypeError()
        self.series_list = series_list

    def get_targets(self):
        targets = []
        for series in self.series_list:
            targets += series.get_targets()
        return targets

    def _post_process_series(self, data):
        new_data = {}
        for series in self.series_list:
            new_data.update(series._post_process_series(data))
        return new_data


class CpuSeries(SimpleGraphiteSeries):

    alias = "cpu"

    def get_inner_target(self):
        # Calculate the sum of all time measurements, excluding the "idle" one
        total_wo_idle_sum = 'sumSeries(exclude(%s.cpu-0.*,"idle"))' % (self.head)
        # Calculate the sum of all time measurements
        total_sum = 'sumSeries(%s.cpu-0.*)' % (self.head)
        # Calculate the derivative of each sum
        first_set = 'derivative(%s)' % (total_wo_idle_sum)
        second_set = 'derivative(%s)' % (total_sum)
        # Divide the first with the second sum (wo_idle_sum / total_sum)
        target = "divideSeries(%s,%s)" % (first_set, second_set)
        return target

    def _post_process_series(self, data):
        return {
            'cpu': {
                'cores': 1,
                'utilization': data['cpu'],
            }
        }


class LoadSeries(SimpleGraphiteSeries):

    alias = "load"

    def get_inner_target(self):
        return "%s.load.load.shortterm" % (self.head)


class NetSeries(SimpleGraphiteSeries):

    alias = "net"
    direction = "*"
    iface = "*"

    def __init__(self, uuid, alias="", iface="", direction=""):
        if iface:
            self.iface = iface
        if direction:
            self.direction = direction
        super(NetSeries, self).__init__(uuid, alias=alias)

    def get_inner_target(self):
        return "derivative(sumSeries(%s.interface-%s.if_octets.%s))" % (
            self.head, self.iface, self.direction
        )


class NetRxSeries(NetSeries):

    alias = "net-rx"
    direction = "rx"


class NetTxSeries(NetSeries):

    alias = "net-tx"
    direction = "rx"


class NetAllSeries(CombinedGraphiteSeries):
    """NetAllSeries merges NetRxSeries and NetTxSeries."""

    def __init__(self, uuid):
        series_list = [NetRxSeries(uuid, iface='eth0'),
                       NetTxSeries(uuid, iface='eth0')]
        super(NetAllSeries, self).__init__(uuid, series_list)

    def _post_process_series(self, data):
        return {
            'eth0': {
                'rx': data['net-rx'],
                'tx': data['net-tx'],
            }
        }


class MemSeries(SimpleGraphiteSeries):

    alias = "mem"

    def get_inner_target(self):
        target_used = 'sumSeries(%s.memory.memory-{buffered,cached,used})' % (self.head)
        target_total= 'sumSeries(%s.memory.memory-*)' % (self.head)
        target_perc = 'asPercent(%s, %s)' % (target_used, target_total)
        return target_perc


class DiskSeries(SimpleGraphiteSeries):

    alias = "disk"
    direction = "*"

    def __init__(self, uuid, alias="", direction=""):
        if direction:
            self.direction = direction
        super(DiskSeries, self).__init__(uuid, alias=alias)

    def get_inner_target(self):
        return "derivative(sumSeries(%s.disk-*.%s.%s))" % (
            self.head, 'disk_octets', self.direction
        )


class DiskReadSeries(DiskSeries):

    alias = "disk-read"
    direction = "read"


class DiskWriteSeries(DiskSeries):

    alias = "disk-write"
    direction = "write"


class DiskAllSeries(CombinedGraphiteSeries):

    def __init__(self, uuid):
        series_list = [DiskReadSeries(uuid), DiskWriteSeries(uuid)]
        super(DiskAllSeries, self).__init__(uuid, series_list)

    def _post_process_series(self, data):
        return {
            'disk': {
                'disks': 1,
                'read': {
                    'xvda1': {
                        'disk_octets': data['disk-read'],
                    }
                },
                'write': {
                    'xvda1': {
                        'disk_octets': data['disk-write'],
                    }
                },
            }
        }


class AllSeries(CombinedGraphiteSeries):

    def __init__(self, uuid):
        series_list = [
            CpuSeries(uuid),
            MemSeries(uuid),
            LoadSeries(uuid),
            NetAllSeries(uuid),
            DiskAllSeries(uuid),
        ]
        super(AllSeries, self).__init__(uuid, series_list)
