import time
import json
import Queue
import logging
import requests
import threading
import multiprocessing

from bucky.names import statname

from mist.monitor import config as mon_config
from mist.monitor.graphite import MultiHandler
from mist.monitor.model import get_machine_from_uuid


log = logging.getLogger(__name__)


class NewMetricsObserver(object):
    def __init__(self, path=""):
        self.metrics = set()
        self.queue = multiprocessing.Queue()
        if path:
            # load metrics from file (to persist restart of bucky)
            try:
                f = open(path)
            except IOError as exc:
                log.warning("Error opening metrics file: %s", exc)
            else:
                for line in f:
                    line = line.strip()
                    parts = line.split()
                    if len(parts) == 2:
                        host, name = map(str.strip, parts)
                        self.metrics.add((host, name))
                    else:
                        log.error("Invalid line in '%s': '%s'", path, line)
                log.info("Loaded %d metrics from file", len(self.metrics))
                f.close()
        else:
            log.warning("No path configured to persist discovered metrics")
        self.dispatcher = NewMetricsDispatcher(self.queue, path=path, flush=1)
        self.dispatcher.start()

    def __call__(self, host, name, val, timestamp):
        if (host, name) not in self.metrics:
            try:
                self.queue.put((host, name), block=False)
            except Queue.Full:
                log.warning("Queue full while pushing new metric.")
            else:
                self.metrics.add((host, name))
        return host, name, val, timestamp


class NewMetricsDispatcher(threading.Thread):
    def __init__(self, queue, path="", flush=5):
        super(NewMetricsDispatcher, self).__init__()
        self.queue = queue
        self.daemon = True
        self.flush = flush
        self.ignore_plugins = set([
            "cpu", "df", "md", "thermal", "disk", "entropy", "interface",
            "load", "memory", "processes", "swap", "users", "ping", "network",
        ])
        self.fh = None
        if path:
            try:
                self.fh = open(path, 'a')
            except IOError as exc:
                log.error("Error opening metrics file for writing!")

    def run(self):
        while True:
            start = time.time()
            try:
                self.run_once()
            except Exception as exc:
                log.error("Error in NewMetrisDispatcher: %r", exc)
            elapsed = time.time() - start
            remaining = self.flush - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def run_once(self):
        """Read and parse entire queue and notify core."""
        new_names = {}
        counter = 0
        while True:
            try:
                host, name = self.queue.get(block=False)
            except Queue.Empty:
                break
            if host not in new_names:
                new_names[host] = []
            new_names[host].append(name)
            counter += 1

        for host, names in new_names.items():
            self.dispatch(host, names)

    def dispatch(self, host, names):
        machine = get_machine_from_uuid(host)
        if not machine:
            log.error("machine not found, wtf!")
            return
        multihandler = MultiHandler(host)
        metrics = []
        for name in names:
            target = statname(host, name)
            metric = multihandler.decorate_target(target)
            if metric['alias'].rfind("%(head)s.") == 0:
                metric['alias'] = metric['alias'][9:]
            plugin = metric['alias'].split('.')[0]
            if plugin not in self.ignore_plugins:
                metrics.append(metric)
        if not metrics:
            return
        log.info("New metrics for host %s, notifying core: %s", host, metrics)
        payload = {
            'uuid': host,
            'collectd_password': machine.collectd_password,
            'metrics': metrics,
        }
        try:
            resp = requests.post(
                "%s/new_metrics" % mon_config.CORE_URI,
                data=json.dumps(payload),
                verify=mon_config.SSL_VERIFY
            )
        except Exception as exc:
            log.error("Error notifying core: %r", exc)
            return
        if not resp.ok:
            log.error("Bad response from core: %s", resp.text)
        # also save to file in disk
        if self.fh is not None:
            try:
                for name in names:
                    self.fh.write("%s %s\n" % (host, name))
                self.fh.flush()
            except IOError as exc:
                log.error("Error writing to metrics file: %s", exc)
