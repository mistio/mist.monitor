import time
import json
import Queue
import logging
import requests
import threading
import multiprocessing

from bucky.names import statname

from mist.monitor import config as mon_config
from mist.monitor.model import get_machine_from_uuid


log = logging.getLogger(__name__)


class NewMetricsObserver(object):
    def __init__(self):
        self.metrics = set()
        self.queue = multiprocessing.Queue()
        self.dispatcher = NewMetricsDispatcher(self.queue, flush=1)
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
    def __init__(self, queue, flush=5):
        super(NewMetricsDispatcher, self).__init__()
        self.queue = queue
        self.daemon = True
        self.flush = flush

        self.ignore_plugins = set([
            "cpu", "df", "md", "thermal", "disk", "entropy", "interface",
            "load", "memory", "processes", "swap", "users", "ping", "network",
        ])

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
        new_metrics = {}
        counter = 0
        while True:
            try:
                host, name = self.queue.get(block=False)
            except Queue.Empty:
                break
            metric = statname(host, name).replace("bucky.%s." % host, "")
            plugin = metric.split(".")[0]
            if plugin not in self.ignore_plugins:
                log.info("Found new metric '%s' for host '%s'.", metric, host)
                if host not in new_metrics:
                    new_metrics[host] = []
                new_metrics[host].append(metric)
            counter += 1

        for host, metrics in new_metrics.items():
            self.dispatch(host, metrics)

    def dispatch(self, host, metrics):
        print host, metrics
        machine = get_machine_from_uuid(host)
        if not machine:
            log.warning("machine not found, wtf!")
            return
        payload = {
            'uuid': host,
            'collectd_password': machine.collectd_password,
            'metrics': metrics,
        }
        log.info("Notifying core: %s", payload)
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
