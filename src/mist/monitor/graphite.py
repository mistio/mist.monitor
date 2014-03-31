import abc
import re
import logging
import HTMLParser
import requests
from time import time


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

    def head(self, bucky=False):
        """Top level data target."""
        if not bucky:
            return "mist-%s" % self.uuid
        else:
            return "bucky.%s" % self.uuid

    @abc.abstractmethod
    def get_targets(self, interval_str='', bucky=False):
        """Return list of target strings.

        If interval_str specified, summarize targets accordingly.

        """
        return []

    def get_series(self, start="", stop="", interval_str="",
                   transform_null=None, bucky=False):
        """Get time series from graphite.

        Optional start and stop parameters define time range.
        transform_null defines handling of null values in graphite.
            If transform_null=False, null's are left in place (as None's)
            If transform_null=None, null's are stripped
            If transform_null=value, null values are replaced by value.
        """

        # if start is a timestamp
        if re.match("^[0-9]+(\.[0-9]+)?$", start):
            # Ask for some more cause derivatives will always return None
            # as their first value. Check RETENTIONS from config to find step.
            start = int(start)
            filter_from = start
            ago = time() - start
            for period in sorted(config.RETENTIONS.keys()):
                if ago <= period:
                    step = config.RETENTIONS[period]
                    start -= 2 * step
                    break
            start = str(start)
            # remove interval_str if <= step so that we won't get nulls in
            # between measurements (if <) or last measurement null (if =)
            # only works if interval_str is in seconds
            interval_str_match = re.match("^([0-9]+)(?:sec)?s?$", interval_str)
            if interval_str_match:
                interval_secs = int(interval_str_match.groups()[0])
                if interval_secs <= step:
                    interval_str = ""
        else:
            filter_from = 0

        targets = self.get_targets(interval_str=interval_str, bucky=bucky)
        uri = self._construct_graphite_uri(targets, start, stop)
        resp = self._graphite_request(uri, bucky=bucky)
        data = resp.json()
        if filter_from:
            for item in data:
                item['datapoints'] = [point for point in item['datapoints']
                                      if point[1] >= filter_from]
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

    def _construct_graphite_uri(self, targets, start="", stop=""):
        targets_str = "&".join(["target=%s" % target for target in targets])
        uri = "%s/render?%s&format=json" % (config.GRAPHITE_URI, targets_str)
        if start:
            uri += "&from=%s" % start
        if stop:
            uri += "&until=%s" % stop
        return uri

    def _graphite_request(self, uri, use_session=True, bucky=False):
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

        if not resp.ok:
            # try to parse error message from graphite's HTML error response
            reason = ""
            try:
                search = re.search("(?:Exception|TypeError): (.*)", resp.text)
                if search:
                    reason = search.groups()[0]
                    reason = HTMLParser.HTMLParser().unescape(reason)
            except:
                pass
            if reason == "reduce() of empty sequence with no initial value":
                # This happens when graphite tries to perform certain
                # calculation on an empty series. I think it is caused when
                # using asPercent or divideSeries. The series is empty if it
                # invalid, ie the graphite doesn't know of the underlying
                # raw data series. This could be due to a typo in the target
                # like saying oooctets instead of octets but since we have
                # tested our targets and know they don't have any typos, the
                # only other explanation is that the machine uuid (which is
                # the top level identifier for a graphite series) is wrong.
                # Practically, this happens if graphite has never recieved
                # any data for this machine so it doesn't have any subseries
                # registered. It happens when a machine has never sent data
                # to graphite (perhaps collecd deployment went wrong) and
                # we try to get the CpuUtilization or MemoryUtilization metric.
                # If we try to get another metric, say Load, on such a target,
                # we will get a 200 OK response but the asked target will be
                # missing from the response body.
                # TODO: send a query to "metrics?query=%s" % self.head()
                # to reveal if graphite knows the machine or not.
                if self.check_head(bucky=bucky):
                    reason = ("Trying to do division with empty series, "
                              "the target must be wrong.")
                else:
                    reason = ("Trying to do division with empty series, cause "
                              "the machine never sent Graphite any data.")
            log.error("Got error response from graphite: [%d] %s",
                      resp.status_code, reason or resp.text)
            raise GraphiteError(reason)
        return resp

    def get_metrics(self, expression="", bucky=False):
        query = self.head(bucky=bucky)
        if expression:
            query += ".%s" % (expression)
        url = "%s/metrics?query=%s" % (config.GRAPHITE_URI, query)
        resp = self._graphite_request(url)
        return resp.json()

    def check_head(self, bucky=False):
        return bool(self.get_metrics(bucky=bucky))


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

    @abc.abstractproperty
    def sum_function(self):
        """Must be a string in ['sum', 'avg', 'max', 'min', 'last']."""

    @abc.abstractmethod
    def get_inner_target(self):
        pass

    @abc.abstractmethod
    def get_inner_target_bucky(self):
        pass

    def get_targets(self, interval_str="", bucky=False):
        if bucky:
            target = self.get_inner_target_bucky()
        else:
            target = self.get_inner_target()
        if interval_str:
            target = "summarize(%s,'%s','%s')" % (target, interval_str,
                                                  self.sum_function)
        target = "alias(%s,'%s')" % (target, self.alias)
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

    def get_targets(self, interval_str="", bucky=False):
        targets = []
        # join all child series targets
        for series in self.series_list:
            targets += series.get_targets(interval_str=interval_str,
                                          bucky=bucky)
        # remove duplicates (using a dict since lookup is a lot faster)
        seen = {}
        uniq_targets = []
        for target in targets:
            if target in seen:
                continue
            seen[target] = 1
            uniq_targets.append(target)
        return uniq_targets

    def _post_process_series(self, data, transform_null=None):
        new_data = {}
        for series in self.series_list:
            new_data.update(series._post_process_series(data, transform_null))
        return new_data


class CpuUtilSeries(SimpleSingleGraphiteSeries):
    """Return CPU utilization as a percentage."""

    alias = "cpu-util"
    sum_function = "avg"

    def get_inner_target(self):
        # Calculate the sum of all time measurements, excluding the "idle" one
        total_wo_idle_sum = "sumSeries(exclude(%s.cpu-0.*,'idle'))" % self.head()
        # Calculate the sum of all time measurements
        total_sum = "sumSeries(%s.cpu-0.*)" % self.head()
        # Calculate the derivative of each sum
        first_set = "nonNegativeDerivative(%s)" % total_wo_idle_sum
        second_set = "nonNegativeDerivative(%s)" % total_sum
        # Divide the first with the second sum (wo_idle_sum / total_sum)
        #target = "divideSeries(%s,%s)" % (first_set, second_set)
        target = "asPercent(%s,%s)" % (first_set, second_set)
        return target

    def get_inner_target_bucky(self):
        head = self.head(bucky=True)
        non_idle = "sumSeries(exclude(%s.cpu.*.*,'idle'))" % head
        total = "sumSeries(%s.cpu.*.*)" % head
        perc = "asPercent(%s,%s)" % (non_idle, total)
        return perc


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
    sum_function = "avg"

    def get_inner_target(self):
        return "%s.load.load.shortterm" % (self.head())

    def get_inner_target_bucky(self):
        return "%s.load.shortterm" % self.head(bucky=True)


class NetSeries(SimpleSingleGraphiteSeries):

    alias = "net"
    sum_function = "avg"
    direction = "*"  # '*', 'rx', 'tx'
    iface = "*"  # '*', 'eth0', 'eth*' etc

    def __init__(self, uuid, alias="", iface="", direction=""):
        if iface:
            self.iface = iface
        if direction:
            self.direction = direction
        super(NetSeries, self).__init__(uuid, alias=alias)

    def get_inner_target(self):
        # collectd version 4.10 uses 'interface.if_octets-eth0' format
        # collectd version 5.1  uses 'interface-eth0.if_octets' format
        # we use the {-eth0,} filter in both places to catch both cases
        raw_series = "%s.interface{-%s,}.if_octets{-%s,}.%s" % \
            (self.head(), self.iface, self.iface, self.direction)
        net_util = "scaleToSeconds(sumSeries(nonNegativeDerivative(%s)),1)" % \
            (raw_series, )
        return net_util

    def get_inner_target_bucky(self):
        return "%s.interface.%s.if_octets.%s" % (
            self.head(bucky=True), self.iface, self.direction
        )


class NetRxSeries(NetSeries):

    alias = "net-rx"
    direction = "rx"


class NetTxSeries(NetSeries):

    alias = "net-tx"
    direction = "tx"


class NetAllSeries(CombinedGraphiteSeries):
    """NetAllSeries merges NetRxSeries and NetTxSeries."""

    def __init__(self, uuid):
        series_list = [NetRxSeries(uuid, iface='eth*'),
                       NetTxSeries(uuid, iface='eth*')]
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
    sum_function = "avg"

    def get_inner_target(self):
        target_used = 'sumSeries(%s.memory.memory-{buffered,cached,used})' % (self.head())
        target_total= 'sumSeries(%s.memory.memory-*)' % (self.head())
        target_perc = 'asPercent(%s, %s)' % (target_used, target_total)
        return target_perc

    def get_inner_target_bucky(self):
        head = self.head(bucky=True)
        non_free = "sumSeries(%s.memory.{buffered,cached,used})" % head
        total = "sumSeries(%s.memory.*)" % head
        perc = "asPercent(%s,%s)" % (non_free, total)
        return perc


class DiskSeries(SimpleSingleGraphiteSeries):

    alias = "disk"
    sum_function = "avg"
    direction = "*"
    disk = "*"

    def __init__(self, uuid, alias="", direction="", disk=""):
        if direction:
            self.direction = direction
        if disk:
            self.disk = disk
        super(DiskSeries, self).__init__(uuid, alias=alias)

    def get_inner_target(self):
        return "scaleToSeconds(nonNegativeDerivative(sumSeries(%s.disk-*.%s.%s)),1)" % (
            self.head(), 'disk_octets', self.direction
        )

    def get_inner_target_bucky(self):
        return "sumSeries(%s.disk.%s.disk_octets.%s)" % (
            self.head(bucky=True), self.disk, self.direction
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
