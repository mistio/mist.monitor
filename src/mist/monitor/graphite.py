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


def summarize(series, interval, function):
    return "summarize(%s,'%s','%s')" % (series, interval, function)


def sum_series(series_list):
    return "sumSeries(%s)" % series_list


def as_percent(series_list, total=None):
    if total:
        return "asPercent(%s,%s)" % (series_list, total)
    else:
        return "asPercent(%s) % series_list"


def exclude(series_list, regex):
    return "exclude(%s,'%s')" % (series_list, regex)


class BaseGraphiteSeries(object):
    """Base graphite target class that defines an interface and provides
    convenience methods for subclasses to use."""

    __metaclass__ = abc.ABCMeta

    def __init__(self, uuid):
        """A uuid is required to initialize the class."""
        self.uuid = uuid

    def head(self):
        """Top level data target."""
        return "bucky.%s" % self.uuid

    @abc.abstractmethod
    def get_targets(self, interval_str=''):
        """Return list of target strings.

        If interval_str specified, summarize targets accordingly.

        """
        return []

    def get_series(self, start="", stop="", interval_str="", process=True):
        """Get time series from graphite.

        Optional start and stop parameters define time range.

        """

        # if start is a timestamp
        if re.match("^[0-9]+(\.[0-9]+)?$", start):
            # Ask for some more cause derivatives will always return None
            # as their first value. Check RETENTIONS from config to find step.
            start = int(start)
            filter_from = start
            ago = time() - start
            step = 0
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

        targets = self.get_targets(interval_str=interval_str)
        uri = self._construct_graphite_uri(targets, start, stop)
        resp = self._graphite_request(uri)
        data = resp.json()
        if filter_from:
            for item in data:
                item['datapoints'] = [point for point in item['datapoints']
                                      if point[1] >= filter_from]
        if process:
            data = self.post_process_series(data)
        return data

    def post_process_series(self, data):
        return data

    def _construct_graphite_uri(self, targets, start="", stop=""):
        targets_str = "&".join(["target=%s" % target for target in targets])
        uri = "%s/render?%s&format=json" % (config.GRAPHITE_URI, targets_str)
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
                if self.check_head():
                    reason = ("Trying to do division with empty series, "
                              "the target must be wrong.")
                else:
                    reason = ("Trying to do division with empty series, cause "
                              "the machine never sent Graphite any data.")
            log.error("Got error response from graphite: [%d] %s",
                      resp.status_code, reason or resp.text)
            raise GraphiteError(reason)
        return resp

    def _find_metrics(self, query):
        url = "%s/metrics?query=%s" % (config.GRAPHITE_URI, query)
        resp = self._graphite_request(url)
        return resp.json()

    def check_head(self):
        return bool(self._find_metrics(self.head()))

    def find_metrics(self, strip_head=False):
        def find_leaves(query):
            leaves = []
            for metric in self._find_metrics(query):
                if metric['leaf']:
                    leaves.append(metric['id'])
                elif metric['allowChildren']:
                    # or metric['expandable']
                    leaves += find_leaves(metric['id'] + ".*")
            return leaves

        query = "%s.*" % self.head()
        leaves = find_leaves(query)
        if strip_head:
            prefix = "%s." % self.head()
            leaves = [leaf.replace(prefix, "%(head)s.") for leaf in leaves]
        return leaves


class SingleGraphiteSeries(BaseGraphiteSeries):
    """A SingleGraphiteSeries returns a single graphite data series.

    """

    alias = ""

    def __init__(self, uuid, alias=""):
        super(SingleGraphiteSeries, self).__init__(uuid)
        if alias:
            self.alias = alias


class SimpleSingleGraphiteSeries(SingleGraphiteSeries):
    """The simplest case of a SingleGraphiteSeries, using a single target."""

    def __init__(self, uuid, alias=""):
        super(SimpleSingleGraphiteSeries, self).__init__(uuid, alias=alias)
        self._last_name = ""

    def sum_function(self):
        """Returns the function should be used when summarizing data.

        Must be a string in ['sum', 'avg', 'max', 'min', 'last'].

        """
        return "avg"

    @abc.abstractmethod
    def get_inner_target(self):
        pass

    def get_targets(self, interval_str=""):
        target = self.get_inner_target()
        if interval_str:
            target = summarize(target, interval_str, self.sum_function)
        if self.alias and self.alias != target:
            target = "alias(%s,'%s')" % (target, self.alias)
            self._last_name = self.alias
        else:
            self._last_name = target
        return [target]

    def post_process_series(self, data):
        """Only parse relevant data."""
        if not self._last_name:
            log.error("Called post_process_series but no self._last_name")
            return []
        for item in data:
            if item['target'] == self._last_name:
                return super(SimpleSingleGraphiteSeries,
                             self).post_process_series([item])
        return []


class CustomSingleGraphiteSeries(SimpleSingleGraphiteSeries):
    def __init__(self, uuid, target, alias=""):
        super(CustomSingleGraphiteSeries, self).__init__(uuid, alias=alias)
        self._target = target

    def get_inner_target(self):
        return self._target % {'head': self.head()}


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

    def get_targets(self, interval_str=""):
        targets = []
        # join all child series targets
        for series in self.series_list:
            targets += series.get_targets(interval_str=interval_str)
        # remove duplicates (using a dict since lookup is a lot faster)
        seen = {}
        uniq_targets = []
        for target in targets:
            if target in seen:
                continue
            seen[target] = 1
            uniq_targets.append(target)
        return uniq_targets

    def post_process_series(self, data):
        new_data = []
        for series in self.series_list:
            new_data += series.post_process_series(data)
        return new_data


class CpuUtilSeries(SimpleSingleGraphiteSeries):
    """Return CPU utilization as a percentage."""

    alias = "cpu"

    def get_inner_target(self):
        return as_percent(
            sum_series(exclude("%s.cpu.*.*" % self.head(), 'idle')),
            sum_series("%s.cpu.*.*" % self.head())
        )


class LoadSeries(SimpleSingleGraphiteSeries):

    alias = "load"

    def get_inner_target(self):
        return "%s.load.shortterm" % self.head()


class NetSeries(SimpleSingleGraphiteSeries):

    alias = "net"

    def __init__(self, uuid, iface, direction, alias=""):
        super(NetSeries, self).__init__(uuid, alias=alias)
        self.iface = iface
        self.direction = direction

    def get_inner_target(self):
        return "%s.interface.%s.if_octets.%s" % (
            self.head(), self.iface, self.direction
        )


class WildcardNetSeries(NetSeries):
    def get_inner_target(self):
        return sum_series(super(WildcardNetSeries, self).get_inner_target())


class NetEthRxSeries(WildcardNetSeries):
    def __init__(self, uuid, alias="network-rx"):
        super(NetEthRxSeries, self).__init__(uuid, alias=alias,
                                             iface="eth*", direction="rx")


class NetEthTxSeries(WildcardNetSeries):
    def __init__(self, uuid, alias="network-tx"):
        super(NetEthTxSeries, self).__init__(uuid, alias=alias,
                                             iface="eth*", direction="tx")


class NetAllSeries(CombinedGraphiteSeries):
    """NetAllSeries merges NetRxSeries and NetTxSeries."""

    def __init__(self, uuid):
        series_list = [NetEthRxSeries(uuid), NetEthTxSeries(uuid)]
        super(NetAllSeries, self).__init__(uuid, series_list)


class MemSeries(SimpleSingleGraphiteSeries):

    alias = "ram"

    def get_inner_target(self):
        return as_percent(
            sum_series("%s.memory.{buffered,cached,used}" % self.head()),
            sum_series("%s.memory.*" % self.head())

        )


class DiskSeries(SimpleSingleGraphiteSeries):

    alias = "disk"

    def __init__(self, uuid, direction, disk, alias=""):
        super(DiskSeries, self).__init__(uuid, alias=alias)
        self.direction = direction
        self.disk = disk

    def get_inner_target(self):
        return "%s.disk.%s.disk_octets.%s" % (
            self.head(), self.disk, self.direction
        )


class WildcardDiskSeries(DiskSeries):
    def get_inner_target(self):
        return sum_series(super(WildcardDiskSeries, self).get_inner_target())


class DiskAllReadSeries(WildcardDiskSeries):
    def __init__(self, uuid, alias="disk-read"):
        super(DiskAllReadSeries, self).__init__(uuid, alias=alias,
                                                disk="*", direction="read")


class DiskAllWriteSeries(WildcardDiskSeries):
    def __init__(self, uuid, alias="disk-write"):
        super(DiskAllWriteSeries, self).__init__(uuid, alias=alias,
                                                 disk="*", direction="write")


class DiskAllSeries(CombinedGraphiteSeries):

    def __init__(self, uuid):
        series_list = [DiskAllReadSeries(uuid), DiskAllWriteSeries(uuid)]
        super(DiskAllSeries, self).__init__(uuid, series_list)


class AllSeries(CombinedGraphiteSeries):
    """This combines several series (used by get_stats)"""

    def __init__(self, uuid):
        series_list = [
            CpuUtilSeries(uuid),
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


    def post_process_series(self, data):
        """transform_null is ignored here."""
        points = {}
        for series in self.series_list:
            tmp_data = series.post_process_series(data)
            for item in tmp_data:
                for value, timestamp in item['datapoints']:
                    if timestamp not in points:
                        points[timestamp] = 1
                    if value is not None:
                        points[timestamp] = 0
        if not points:
            points[0] = 1
        return [{
            'target': self.alias,
            'datapoints': [(points[ts], ts) for ts in sorted(points.keys())]
        }]
