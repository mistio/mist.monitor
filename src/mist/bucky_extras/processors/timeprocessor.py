import logging
from time import time


log = logging.getLogger(__name__)


class TimeDiff(object):
    """Drop all samples with timestamp far away in the past or future."""

    def __init__(self, past=None, future=None):
        """past and future threshold in seconds as positive ints"""

        self.past = past
        self.future = future

    def __call__(self, host, name, val, timestamp):
        offset = round(timestamp - time())
        if self.future is not None and offset > self.future:
            return None
        if self.past is not None and offset < -self.past:
            return None
        return host, name, val, timestamp


class TimeConverter(object):
    """Fix timestamps on samples

    Observe the apparent time offset per host and fixes timestamps accordingly.
    We make the assumption that the host's clock isn't wildly jumping back and
    forth but may have a time offset and a slow drift and may also occasionally
    have his clock changed.

    We account for variable delay in the time elapsed from the sample being
    collectd until it gets to us. We try to subtract a constant estimated
    offset from the samples in order not to mess with data accuracy.

    For a relatively stable clock with time skew real_off and a variable delay
    up to max_delay, the observed offset (sample timestamp - current time) is
    obs_off and:
        real_off - max_delay <= obs_off <= real_off
    The cached estimated offset est_off is changed when a higher obs_off is
    observed so that it quickly converges to the upper bound for obs_off
    (more accurate estimation). This also deals with large jumps ahead in time.
    Jumps/drifts backwards in times change the est_off when they differ more
    than max_delay to account for the variable delay in samples.

    This practically means that it basically works, the processed samples have
    good accuracy. Large changes in offset may cause temporary hick ups in
    data (both here but also in the collectd server). The sensitivity at which
    slow drifts backwards in time change the est_off depends on max_delay.
    Setting it too high will cause inaccuracies in slow negative drifts,
    setting it to low may cause ever changing est_off.

    """

    def __init__(self, max_delay):
        self.max_delay = max_delay

    def __call__(self, host, name, val, timestamp):

        # host's clock skew <=> offset (+ in the future, - in the past) in secs
        offset = int(round(timestamp - time()))
        known_offset = self.get_offset(host)
        # if offset larger or way smaller, change known_offset
        if offset > known_offset or known_offset - offset > self.max_delay:
            self.set_offset(host, offset)
            log.info("Host '%s': offset changed from %d to %d.",
                     host, known_offset, offset)
            known_offset = offset

        # remove estimated offset from timestamp
        timestamp -= known_offset
        return host, name, val, timestamp

    def get_offset(self, host):
        raise NotImplementedError

    def set_offset(self, host, offset):
        raise NotImplementedError


class TimeConverterSingleThread(TimeConverter):
    """Stores the cached offsets in a dict, works well but not thread safe."""

    def __init__(self, max_delay):
        super(TimeConverterSingleThread, self).__init__(max_delay)
        self._offset_map = {}

    def get_offset(self, host):
        return self._offset_map.get(host, 0)

    def set_offset(self, host, offset):
        self._offset_map[host] = offset

