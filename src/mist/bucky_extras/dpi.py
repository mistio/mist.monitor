import time
import logging
import collections


log = logging.getLogger(__name__)


class PacketReporter(object):
    def __init__(self, interval=60, allowed_errors=0, total_max=None,
                 repeat=float('inf')):
        self.pkts = collections.defaultdict(
            lambda: collections.defaultdict(int)
        )
        self.interval = interval
        self.allowed_errors = allowed_errors
        self.total_max = total_max or float('inf')
        self.last_process = time.time()
        self.repeat = repeat
        self.count_runs = 0

    def __call__(self, ip_addr, port, data, exc):
        if self.count_runs > self.repeat:
            return
        res = str(exc) if isinstance(exc, Exception) else 'ok'
        self.pkts[ip_addr][res] += 1
        if time.time() - self.last_process >= self.interval:
            self.last_process = time.time()
            self.process()
            self.count_runs += 1

    def process(self):
        suspect_ips = []
        for ip_addr in self.pkts:
            total = sum(self.pkts[ip_addr].values())
            good = self.pkts[ip_addr]['ok']
            bad = total - good
            errors = [key for key in self.pkts[ip_addr] if key != 'ok']
            if total > self.total_max:
                errors.append("Too many packets received.")
                suspect_ips.append((ip_addr, True, good, bad, errors))
            if bad:
                if bad > self.allowed_errors:
                    if not good:
                        suspect_ips.append((ip_addr, True, good, bad, errors))
                    else:
                        suspect_ips.append((ip_addr, False, good, bad, errors))
                else:
                    suspect_ips.append((ip_addr, False, good, bad, errors))

        text = ""
        for ip_addr, block, good, bad, errors in suspect_ips:
            if not block:
                text += "#"
            text += "%s # ok/error/total=%d/%d/%d. Errors occured: %s\n" % (
                ip_addr, good, bad, good + bad, errors
            )
        if not text:
            text = "No suspect ip's found"
        log.info(text)
        self.pkts.clear()
