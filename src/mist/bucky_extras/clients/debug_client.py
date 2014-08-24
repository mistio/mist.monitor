import sys
import time
import datetime

from bucky.client import Client
from bucky.names import statname


class DebugClient(Client):
    out_path = None

    def __init__(self, cfg, pipe):
        super(DebugClient, self).__init__(pipe)
        if self.out_path:
            self.stdout = open(self.out_path, 'w')
        else:
            self.stdout = sys.stdout

    def send(self, host, name, value, tstamp):
        if self.filter(host, name, value, tstamp):
            self.write(host, name, value, tstamp)

    def filter(self, host, name, value, tstamp):
        return True

    def write(self, host, name, value, tstamp):
        target = statname(host, name)
        dtime = datetime.datetime.fromtimestamp(tstamp)
        time_lbl = dtime.strftime('%y%m%d %H:%M:%S')
        self.stdout.write('%s (%.1fs) %s %r\n' % (time_lbl,
                                                  tstamp - time.time(),
                                                  target, value))
        self.stdout.flush()
