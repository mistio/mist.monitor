import abc
import requests

from mist.monitor.exceptions import GraphiteError


MACHINE_PREFIX = "mist"

REQ_SESSION = None


class GraphiteTarget(object):
    """Base graphite target class that defines an interface and provides
    convinience methods for subclasses to use."""

    __metaclass__ = abc.ABCMeta

    def __init__(self, uuid)
        self.head = "%s-%s" % (MACHINE_PREFIX, uuid)

    @abc.abstractproperty
    def alias(self):
        """Each base class must define an 'alias' property."""

    def _wrap_target(self, target):
        """Prepare target and add the alias."""
        return "target=alias(%s,'%s')" % (target, self.alias)

    @abc.abstractmethod
    def get_series_target(self):
        """Construct a graphite target string to retrieve time series."""

    def get_series(self):
        """Get time series from graphite."""
        return self._graphite_request(self.get_series_target())

    @abc.abstractmethod
    def get_value_target(self):
        """Construct a graphite target string to retrieve single value."""

    def get_value(self):
        """Get single value from graphite."""
        return self._graphite_request(self.get_value_target())

    def _graphite_request(self, target, use_session=False):
        """Issue a request to graphite."""

        # FIXME: construct uri from target somehow

        global REQ_SESSION

        if use_session:
            log.debug("Using turbo http session")
            REQ_SESSION = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
            REQ_SESSION.mount('http://', adapter)
            REQ_SESSION.keep_alive = True
            req = REQ_SESSION
        else:
            req = requests

        try:
            resp = req.get(uri)
        except Exception as exc:
            log.error("Error sending request to graphite: %r", exc)
            raise GraphiteError(repr(exc))

        if resp.status_code != 200:
            log.error("Got error response from graphite: [%d] %s",
                      resp.status_code, resp.text)
            raise GraphiteError()

        return {item['target']: item['datapoints'] for item in resp.json()}


class CpuTarget(GraphiteTarget):

    alias = "cpu"

    def get_series_target_unwrapped(self):
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

    def get_series_target(self):
        return self._wrap_target(self.get_series_target_unwrapped())

    def get_value_target(self):
        raise NotImplementedError()

    def get_series(self, time)

        self._graphite_request(target)

        #FIXME: curently aggregates utilization for all CPUs -- thus we pass 1 to D3
        cpu_data = {'utilization': [], 'cores': 1}

        target = self.get_series_target()

        complete_uri = "%s/render?target=transformNull(%s, 0)%s&format=json" % (uri, target, time)

        list_data = graphite_issue_request(complete_uri)

        cpu_data['utilization'] = list_data

        if not list_data:
            log.warn("cpu utilization data empty :S")

        ret = cpu_data

        return ret


class LoadTarget(GraphiteTarget):

    alias = "load"

    def get_series_target_unwrapped(self):
        return "%s.load.load.shortterm" % (self.head)

    def get_series_target(self):
        return self._wrap_target(self.get_series_target_unwrapped())

    def get_value_target(self):
        raise NotImplementedError()

        target = self.get_series_target()

        load_data = []

        complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time)

        list_data = graphite_issue_request(complete_uri)

        load_data = list_data

        if not list_data:
            log.warn("LOAD data empty :S")

        ret = load_data
        return ret


class NetTarget(GraphiteTarget):

    alias = "net"

    def __init__(self, uuid, iface="", direction=""):
        self.iface = iface if iface == "eth0" else "*"
        self.direction = direction if direction in ["rx", "tx"] else "*"
        super(NetTarget, self).__init__(uuid)

    def get_series_target_unwrapped(self):
        return "derivative(sumSeries(%s.interface-%s.if_octets.%s))" % (
            self.head, self.iface, self._direction
        )

    def get_series_target(self):
        return self._wrap_target(self.get_series_target_unwrapped())

    def get_value_target(self):
        target = self.get_series_target_unwrapped()
        target = 'summarize(%s, "STEPsecs", "avg")' % (target)
        target = "transformNull(removeBelowValue(%s, 0), 0)" % (target)
        target = self._wrap_target(target)
        return target


class NetRxTarget(NetTarget):

    alias = "net-send"

    def __init__(self, uuid, iface=""):
        super(NetRxTarget, self).__init__(uuid, iface, "rx")


class NetTxTarget(NetTarget):

    alias = "net-recv"

    def __init__(self, uuid, iface=""):
        super(NetTxTarget, self).__init__(uuid, iface, "tx")


class NetTarget(GraphiteTarget):
    """NetTarget merges NetRxTarget and NetTxTarget."""

    alias = "net"

    def get_series_target(self):
        net_rx = NetRxTarget(self.uuid)
        rx_target = net_rx.wrap_target(net_rx.get_series_target())
        net_tx = NetTxTarget(self.uuid)
        tx_target = net_tx.wrap_target(net_tx.get_series_target())
        target = "%s&%s" % (rx_target, tx_target)
        return target

    def get_value_target(self):
        raise NotImplementedError()

    def graphite_get_net_stats(uri, uuid, time):

        #FIXME: curently works for a single interface
        net_data = { 'eth0': { 'rx': [], 'tx': []} }

        vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)

        #FIXME: we may want to return KB instead of just bytes -- if we do, we have to
        #scale to 1/1024
        #FIXME: find a way to handle rx and tx at the same time. Maybe we could get graphite
        #to return a dict with 2 lists, 'tx' and 'rx'.
        #target = 'scale(derivative(%s.interface-eth0.if_octets.tx), 0.00012207031250000000)'
        target = 'derivative(%s.interface-eth0.if_octets.tx)' % (vm_hostname)

        complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time)

        list_data = graphite_issue_request(complete_uri)

        net_data['eth0']['tx'] = list_data

        if not list_data:
            log.warn("NET TX data empty :S")

        target = 'derivative(%s.interface-eth0.if_octets.rx)' % (vm_hostname)

        complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time)

        list_data = graphite_issue_request(complete_uri)

        net_data['eth0']['rx'] = list_data

        if not list_data:
            log.warn("NET RX data empty :S")

        ret = net_data
        return ret


class MemTarget(GraphiteTarget):

    alias = "mem"

    def get_series_target(self):
        target_used = 'sumSeries(%s.memory.memory-{buffered,cached,used})' % (self.head)
        target_total= 'sumSeries(%s.memory.memory-*)' % (self.head)
        target_perc = 'asPercent(%s, %s)' % (target_used, target_total)

        return target_perc

    def get_value_target(self):
        raise NotImplementedError()

    def graphite_get_mem_stats(uri, uuid, time):

        mem_data = {'total': 0, 'used': [] }

        vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)

        #FIXME: find a way to calculate the total memory without querying graphite!

        target = 'scale(sumSeries(%s.memory.memory-*),0.00097656250000000000)' % (vm_hostname)

        complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time)

        list_data = graphite_issue_request(complete_uri)

        if not list_data:
            log.warn("MEM data empty :S")
            return mem_data

        mem_data['total'] = list_data[0]

        target = 'scale(sumSeries(%s.memory.memory-{buffered,cached,used}),0.00097656250000000000)' % (vm_hostname)

        complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time)

        list_data = graphite_issue_request(complete_uri)

        mem_data['used'] = list_data

        if not list_data:
            log.warn("MEM data empty :S")

        ret = mem_data
        return ret


def make_complex_graphite_target(*args):

    class ComplexTarget(GraphiteTarget):
        def get_series_target(self):
            return "&".join([arg.get_series_target() for arg in args])

    for arg in args:
        if not isinstance(arg, GraphiteTarget):
            raise TypeError(arg)

    return ComplexTarget()
