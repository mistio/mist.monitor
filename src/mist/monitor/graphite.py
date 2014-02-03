import abc
import logging
import requests

from mist.monitor import config
from mist.monitor.exceptions import GraphiteError


REQ_SESSION = None

log = logging.getLogger(__name__)


class BaseGraphiteSeries(object):
    """Base graphite target class that defines an interface and provides
    convenience methods for subclasses to use."""

    __metaclass__ = abc.ABCMeta

    def __init__(self, uuid):
        """A uuid is required to initialize the class."""
        self.uuid = uuid

    @property
    def head(self):
        """Top level data target."""
        return "mist-%s" % (self.uuid)

    @abc.abstractmethod
    def get_targets(self):
        """Return list of target strings."""
        return []

    def get_series(self, start=0, stop=0, transform_null=None):
        """Get time series from graphite.

        Optional start and stop parameters define time range.
        transform_null defines handling of null values in graphite.
            If transform_null=False, null's are left in place (as None's)
            If transform_null=None, null's are stripped
            If transform_null=value, null values are replaced by value.
        """
        uri = self._construct_graphite_uri(self.get_targets(), start, stop)
        data = self._graphite_request(uri)
        return self._post_process_series(data, transform_null=transform_null)

    def _post_process_series(self, data, transform_null=None):
        """Change to (timestamp, value) pairs and process null values.

        transform_null defines handling of null values in graphite.
            If transform_null=False, null's are left in place (as None's)
            If transform_null=None, null's are stripped
            If transform_null=value, null values are replaced by value.

        """

        new_data = {}
        if transform_null is None:
            # strip null values
            for item in data:
                target = item['target']
                new_data[target] = [(timestamp, value)
                                    for value, timestamp in item['datapoints']
                                    if value is not None]
        elif transform_null is False:
            # leave null's as is (None's)
            for item in data:
                target = item['target']
                new_data[target] = [(timestamp, value)
                                    for value, timestamp in item['datapoints']]
        else:
            # transform null values
            for item in data:
                target = item['target']
                new_data[target] = [
                    (timestamp, value if value is not None else transform_null)
                    for value, timestamp in item['datapoints']
                ]
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

    def _graphite_request(self, uri, use_session=True):
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


class SingleGraphiteSeries(BaseGraphiteSeries):
    """A SingleGraphiteSeries returns a single graphite data series.

    Every subclass needs to define an alias property.
    It must always return a single series inside a dict, using the alias as
    key.

    """

    @abc.abstractproperty
    def alias(self):
        return ""

    def __init__(self, uuid, alias=""):
        super(SingleGraphiteSeries, self).__init__(uuid)
        if alias:
            self.alias = alias


class SimpleSingleGraphiteSeries(SingleGraphiteSeries):
    """The simplest case of a SingleGraphiteSeries, using a single target."""

    @abc.abstractmethod
    def get_inner_target(self):
        pass

    def get_targets(self):
        target = "alias(%s,'%s')" % (self.get_inner_target(), self.alias)
        return [target]

    def _post_process_series(self, data, transform_null=None):
        """Only parse relevant data."""
        for item in data:
            if item['target'] == self.alias:
                return super(SimpleSingleGraphiteSeries,
                             self)._post_process_series([item], transform_null)
        return {self.alias: []}


class CombinedGraphiteSeries(BaseGraphiteSeries):
    """Combines multiple GraphiteSeries instances together."""

    def __init__(self, uuid, series_list=None):
        """series should be a list of GraphiteSeries instances."""
        super(CombinedGraphiteSeries, self).__init__(uuid)
        for series in series_list:
            if not isinstance(series, BaseGraphiteSeries):
                raise TypeError("%r is not instance of "
                                "BaseGraphiteSeries." % series)
        self.series_list = series_list

    def get_targets(self):
        targets = []
        for series in self.series_list:
            targets += series.get_targets()
        return targets

    def _post_process_series(self, data, transform_null=None):
        new_data = {}
        for series in self.series_list:
            new_data.update(series._post_process_series(data, transform_null))
        return new_data


class CpuUtilSeries(SimpleSingleGraphiteSeries):
    """Return CPU utilization as a percentage."""

    alias = "cpu-util"
    ## reduce_function = "avg"

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


class CpuAllSeries(CombinedGraphiteSeries):
    """Return all CPU data in a nested dict."""

    def __init__(self, uuid):
        series_list = [CpuUtilSeries(uuid)]
        super(CpuAllSeries, self).__init__(uuid, series_list)

    def _post_process_series(self, data, transform_null=None):
        data = super(CpuAllSeries, self)._post_process_series(data, transform_null)
        return {
            'cpu': {
                'cores': 1,
                'utilization': data[self.series_list[0].alias],
            }
        }


class LoadSeries(SimpleSingleGraphiteSeries):

    alias = "load"
    ## reduce_function = "avg"

    def get_inner_target(self):
        return "%s.load.load.shortterm" % (self.head)


class NetSeries(SimpleSingleGraphiteSeries):

    alias = "net"
    ## reduce_function = "avg"
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

    def _post_process_series(self, data, transform_null=None):
        data = super(NetAllSeries, self)._post_process_series(data, transform_null)
        return {
            'network': {
                'eth0': {
                    'rx': data[self.series_list[0].alias],
                    'tx': data[self.series_list[1].alias],
                }
            }
        }


class MemSeries(SimpleSingleGraphiteSeries):

    alias = "memory"
    ## reduce_function = "avg"

    def get_inner_target(self):
        target_used = 'sumSeries(%s.memory.memory-{buffered,cached,used})' % (self.head)
        target_total= 'sumSeries(%s.memory.memory-*)' % (self.head)
        target_perc = 'asPercent(%s, %s)' % (target_used, target_total)
        return target_perc


class DiskSeries(SimpleSingleGraphiteSeries):

    alias = "disk"
    ## reduce_function = "avg"
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

    def _post_process_series(self, data, transform_null=None):
        data = super(DiskAllSeries, self)._post_process_series(data, transform_null)
        return {
            'disk': {
                'disks': 1,
                'read': {
                    'xvda1': {
                        'disk_octets': data[self.series_list[0].alias],
                    }
                },
                'write': {
                    'xvda1': {
                        'disk_octets': data[self.series_list[1].alias],
                    }
                },
            }
        }


class AllSeries(CombinedGraphiteSeries):
    """This combines several series and constructs the nested dict returned
    by get_stats."""

    def __init__(self, uuid):
        series_list = [
            CpuAllSeries(uuid),
            MemSeries(uuid),
            LoadSeries(uuid),
            NetAllSeries(uuid),
            DiskAllSeries(uuid),
        ]
        super(AllSeries, self).__init__(uuid, series_list)


class NoDataSeries(CombinedGraphiteSeries, SingleGraphiteSeries):
    """Special series returning 0 or 1 values depending on whether there are
    any data available."""

    alias = "nodata"

    def __init__(self, uuid, alias=""):
        if alias:
            self.alias = alias
        series_list = [
            #MemSeries(uuid),
            LoadSeries(uuid),
            #CpuUtilSeries(uuid),
        ]
        super(NoDataSeries, self).__init__(uuid, series_list)


    def _post_process_series(self, data, transform_null=None):
        """transform_null is ignored here."""
        # All this is weird. Don't do stuff like this in any other class, plz!
        aliases = [series.alias for series in self.series_list]
        tmp_data = {}
        for item in data:
            if item['target'] in aliases:
                for value, timestamp in item['datapoints']:
                    if timestamp not in tmp_data:
                        tmp_data[timestamp] = []
                    if value is not None:
                        tmp_data[timestamp].append(value)
        new_data = {self.alias: []}
        for timestamp in sorted(tmp_data.keys()):
            if tmp_data[timestamp]:
                new_data[self.alias].append((timestamp, 0))
            else:
                new_data[self.alias].append((timestamp, 1))
        # hack to handle case where graphite knows nothing
        if not new_data[self.alias]:
            new_data[self.alias] = [(0, 1)]
        return new_data
