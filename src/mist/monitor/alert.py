import logging
import requests
from time import time, sleep


from mist.monitor import config
from mist.monitor.model import get_all_machines

from mist.monitor.graphite import CpuSeries
from mist.monitor.graphite import LoadSeries
from mist.monitor.graphite import MemSeries
from mist.monitor.graphite import DiskWriteSeries
from mist.monitor.graphite import NetTxSeries

from mist.monitor.exceptions import ConditionNotFoundError


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
ch = logging.StreamHandler()
log.addHandler(ch)


METRICS_MAP = {
    'cpu': CpuSeries,
    'load': LoadSeries,
    'ram': MemSeries,
    'disk-write': DiskWriteSeries,
    'disk': DiskWriteSeries,  # to gracefully handle old rules (TODO:investigate)
    'network-tx': NetTxSeries,
}


OPERATORS_MAP = {
    'gt': lambda x, y: x > type(x)(y),
    'lt': lambda x, y: x < type(x)(y),
}


NOTIFICATIONS_TIMINGS = [
    0,
    60,
    300,
    600,
]


def notify_core(condition, value):
    if not condition.state:
        log.debug("sending OK to core")
    else:
        log.debug("sending WARNING to core")
    log.debug("uuid:%s", condition.uuid)
    log.debug("rule_id:%s", condition.rule_id)
    log.debug("condition:%s", condition)
    log.debug("value:%s", value)

    machine = condition.get_machine()

    params = {
        'machine_uuid': condition.uuid,
        'machine_password': machine.collectd_password,  # used for auth to core
        'rule_id': condition.rule_id,
        'value': value,
        'triggered': int(condition.state),
        'since': int(condition.state_since),
        'notification_level': condition.notification_level,
    }
    resp = requests.put(config.CORE_URI + "/rules", params=params, verify=False)


def check_condition(condition):

    log.info("Checking %s:%s:'%s'", condition.uuid, condition.rule_id, condition)

    if condition.metric not in METRICS_MAP:
        raise Exception("Bad metric '%s'.", condition.metric)
    if condition.operator not in OPERATORS_MAP:
        raise Exception("Bad operator '%s'.", condition.operator)

    metric = METRICS_MAP[condition.metric]
    operator = OPERATORS_MAP[condition.operator]
    value = metric(condition.uuid).get_value(time()-70)
    if value is None:
        raise Exception("No data")
    triggered = operator(value, condition.value)

    log.info(" * Triggered: %s (value=%s)", triggered, value)
    if triggered:
        # condition just got triggered
        if not condition.state:
            condition.state = True
            condition.state_since = time()
            condition.notification_level = 0
            condition.save()

        # check if we should send alert
        if len(NOTIFICATIONS_TIMINGS) > condition.notification_level:
            duration = time() - condition.state_since
            next_notification = NOTIFICATIONS_TIMINGS[condition.notification_level]
            if duration >= next_notification:
                log.info(" * sending WARNING to core (level=%d, value=%s)",
                         condition.notification_level, value)
                notify_core(condition, value)
                condition.notification_level += 1
                condition.save()

    else:
        if condition.state:
            # condition was previously triggered but not anymore
            condition.state = False
            condition.state_since = time()
            condition.notification_level = 0
            condition.save()
            log.info(" * sending OK to core (value=%s)", value)
            notify_core(condition, value)


def main():
    for machine in get_all_machines():
        for rule_id in machine.rules:
            try:
                condition = machine.get_condition(rule_id)
            except ConditionNotFoundError:
                log.warning("! Condition not found, probably rule just got "
                            "updated. Will check on next run.")
                continue
            try:
                check_condition(condition)
            except Exception as exc:
                log.error(" ! Error %r", exc)


if __name__ == "__main__":
    while True:
        main()
        #raw_input()
        print "=" * 60
        sleep(5)
