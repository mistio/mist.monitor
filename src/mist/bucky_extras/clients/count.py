import time
import logging

from bucky.client import Client


log = logging.getLogger(__name__)


class CountClient(Client):
    interval = 60
    repeat = float('inf')

    def __init__(self, cfg, pipe):
        super(CountClient, self).__init__(pipe)

        # samples[host][name] -> counter of samples
        self.last_flush = time.time()
        self.samples = {}
        self.count_runs = 0

    def send(self, host, name, value, tstamp):
        # host, name = statname(host, name).split('.', 1)
        if self.count_runs >= self.repeat:
            return
        if host not in self.samples:
            self.samples[host] = {name: 1}
            return
        if name not in self.samples[host]:
            self.samples[host][name] = 1
            return
        self.samples[host][name] += 1
        if time.time() - self.last_flush >= self.interval:
            log.info(self.print_stats(self.get_stats()))
            self.samples.clear()
            self.last_flush = time.time()
            self.count_runs += 1

    def get_stats(self, per_sec=True):
        stats = {
            '_total': {
                'samples': 0,
                'samples_per_metric': 0,
                'metrics': 0,
                'hosts': len(self.samples),
                'samples_per_host': 0,
                'metrics_per_host': 0,
            },
        }
        for host in self.samples:
            total = sum(self.samples[host].itervalues())
            stats[host] = {
                'samples': total,
                'samples_per_metric': float(total) / len(self.samples[host]),
                'metrics': len(self.samples[host]),
            }
            stats['_total']['samples'] += total
            stats['_total']['metrics'] += len(self.samples[host])

        tstats = stats['_total']
        samples_per_metric = float(tstats['samples']) / tstats['metrics']
        samples_per_host = float(tstats['samples']) / len(self.samples)
        metrics_per_host = float(tstats['metrics']) / len(self.samples)
        tstats['samples_per_metric'] = samples_per_metric
        tstats['samples_per_host'] = samples_per_host
        tstats['metrics_per_host'] = metrics_per_host
        # calculate per second
        dtime = time.time() - self.last_flush
        for host in stats:
            for name in ('samples', 'samples_per_metric',
                         'samples_per_host'):
                if name in stats[host]:
                    stats[host][name] = float(stats[host][name] / dtime)
        return stats

    def print_stats(self, stats):
        tstats = stats.pop('_total')
        text = "===== TRAFFIC STATS =====\n"
        text += "Hosts: %d\n" % tstats['hosts']
        text += "Metrics: %d\n" % tstats['metrics']
        text += "Samples/Second: %d\n" % tstats['samples']
        text += "Samples/Metric/Second: %.2f\n" % tstats['samples_per_metric']
        text += "Samples/Host/Second: %.2f\n" % tstats['samples_per_host']
        text += "Metrics/Host: %.2f\n" % tstats['metrics_per_host']
        text += "\n\n===== PER HOST STATS =====\n"
        text += "Info: H -> Host, M -> Metric, S -> Sample, s -> second\n\n"
        hosts = sorted(stats.keys(), key=lambda host: stats[host]['samples'],
                       reverse=True)
        for host in hosts:
            text += "H=%s\tM=%d\tS/s=%.2f\tS/M/s=%.2f\n" % (
                host, stats[host]['metrics'], stats[host]['samples'],
                stats[host]['samples_per_metric']
            )
        return text
