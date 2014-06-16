from bucky.collectd import DefaultConverter

class PingConverter(object):
    PRIORITY = 0
    def __init__(self):
        self.default_converter = DefaultConverter()
    def __call__(self, sample):
        print sample
        return self.default_converter(sample)
