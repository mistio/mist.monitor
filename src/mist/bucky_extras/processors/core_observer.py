import time
import json
import Queue
import logging
import requests
import threading
import multiprocessing

from bucky.names import statname


log = logging.getLogger(__name__)


class NewMetricsObserver(object):
    def __init__(self):
        self.metrics = set()
        self.queue = multiprocessing.Queue()
        self.dispatcher = NewMetricsDispatcher(self.queue, flush=10)
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
            prefix = "bucky.%s." % host
            metric = statname(host, name).replace(prefix, "%(head)s.")
            log.info("Found new metric '%s' for host '%s'.", metric, host)
            if host not in new_metrics:
                new_metrics[host] = []
            new_metrics[host].append(metric)
            counter += 1

        if new_metrics:
            log.info("Notifying core about %d new metrics for %d hosts.",
                     counter, len(new_metrics))
            payload = json.dumps(new_metrics)
            log.info("Request payload is %d bytes.", len(payload))
