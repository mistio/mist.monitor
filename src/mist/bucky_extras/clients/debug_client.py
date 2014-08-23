import sys

from bucky.client import Client


class DebugClient(Client):
    out_path = None

    def __init__(self, cfg, pipe):
        super(DebugClient, self).__init__(pipe)
        if self.out_path:
            self.stdout = open(self.out_path, 'w')
        else:
            self.stdout = sys.stdout

    def send(self, host, name, value, time):
        if self.filter(host, name, value, time):
            self.write(host, name, value, time)

    def filter(self, host, name, value, time):
        return True

    def write(self, host, name, value, time):
        self.stdout.write('%s %s %s %s\n' % (host, name, value, time))
        self.stdout.flush()
