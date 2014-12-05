import logging
import requests
from time import time, sleep
from multiprocessing.pool import ThreadPool


from mist.monitor.model import get_all_machines

from mist.monitor.graphite import MultiHandler

from mist.monitor.helpers import tdelta_to_str

from mist.monitor.exceptions import ConditionNotFoundError
from mist.monitor.exceptions import GraphiteError

from mist.monitor import config


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
ch = logging.StreamHandler()
log.addHandler(ch)


def compute(operator, aggregate, values, threshold):
    if aggregate == 'avg':
        # apply avg before operator
        values = [float(sum(values)) / len(values)]
    if operator == 'gt':
        states = {value: value > threshold for value in values}
    elif operator == 'lt':
        states = {value: value < threshold for value in values}
    if aggregate == 'all':
        state = False not in states.values()
        if not state:
            # find retval from false values
            values = [value for value, _state in states.items() if not _state]
    else:
        state = True in states.values()
    if operator == 'gt':
        retval = max(values)
    elif operator == 'lt':
        retval = min(values)
    return state, retval


def notify_core(condition, value):
    """Send rule_triggered notification to mist.core.

    Returns True on success, False otherwise.

    """

    if not condition.state:
        log.debug("sending OK to core")
    else:
        log.debug("sending WARNING to core")

    if condition.metric in ('network-tx', 'disk-write'):
        value = value / 1024  # this metrics are sent and received in KB/s

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
    resp = requests.put(config.CORE_URI + "/rules", params=params,
                        verify=config.SSL_VERIFY)
    if not resp.ok:
        raise Exception(resp.text)


def check_condition(condition, datapoints):

    lbl = "%s:%s [%s]" % (condition.uuid, condition.rule_id, condition)

    # extract value from series and apply operator
    triggered, value = compute(condition.operator,
                               condition.aggregate,
                               [val for val, timestamp in datapoints],
                               condition.value)

    # condition state changed
    if triggered != condition.state:
        condition.state = triggered
        condition.state_since = time()
        # if condition untriggered and no trigger notification previously sent,
        # set level to 1 so that we don't send OK to core (in case condition
        # uses custom reminder list where first notification happens later).
        if not triggered and condition.notification_level == 0:
            condition.notification_level = 1
        else:
            condition.notification_level = 0
        condition.save()

    # logs are gooood
    since_str = "always"
    if condition.state_since:
        since_str = tdelta_to_str(time() - condition.state_since)
        if since_str:
            since_str += " ago"
        else:
            since_str = "just now"
    msg = "%s is %s since %s (value=%s, level=%d)" % (
        lbl, condition.state,since_str, value, condition.notification_level
    )

    # notify core if necessary
    reminder_list = condition.reminder_list or config.REMINDER_LIST
    if condition.state and len(reminder_list) > condition.notification_level:
        duration = time() - condition.state_since
        next_notification = reminder_list[condition.notification_level]
        next_notification += condition.reminder_offset
        if duration < next_notification:
            return
        try:
            notify_core(condition, value)
        except Exception as exc:
            # don't advance notification level if notification failed
            log.error("%s - FAILED to send WARNING: %r", msg, exc)
            return
        log.info("%s - sent WARNING", msg)
        condition.notification_level += 1
        condition.save()
    elif not condition.state and not condition.notification_level:
        try:
            notify_core(condition, value)
        except Exception as exc:
            # don't advance notification level if notification failed
            log.error("%s - FAILED to send OK: %r", msg, exc)
            return
        log.info("%s - sent OK", msg)
        condition.notification_level = 1
        condition.save()
    else:
        log.info(msg)


def check_machine(machine, rule_id=''):
    """Check all conditions for given machine with a single graphite query.

    If rule is specified, on that rule will be checked.

    """

    old_targets = {
        'cpu': 'cpu.total.nonidle',
        'load': 'load.shortterm',
        'ram': 'memory.nonfree_percent',
        'disk-read': 'disk.total.disk_octets.read',
        'disk-write': 'disk.total.disk_octets.write',
        'network-rx': 'interface.total.if_octets.rx',
        'network-tx': 'interface.total.if_octets.tx',
    }

    handler = MultiHandler(machine.uuid)

    # check if machine activated
    if not machine.activated:
        if handler.check_head():
            log.info("%s just got activated after %s", machine.uuid,
                     tdelta_to_str(time() - machine.enabled_time))
            with machine.lock_n_load():
                machine.activated = True
                machine.save()
                for rule_id in machine.rules:
                    condition = machine.get_condition(rule_id)
                    condition.active_after = time() + 30
                    condition.save()
        else:
            log.info("%s not activated since %s", machine.uuid,
                     tdelta_to_str(time() - machine.enabled_time))
        return

    # gather all conditions
    conditions = {}
    rules = [rule_id] if rule_id else machine.rules
    for rule_id in rules:
        lbl = "%s/%s" % (machine.uuid, rule_id)
        try:
            condition = machine.get_condition(rule_id)
        except ConditionNotFoundError:
            log.warning("%s condition not found, probably rule just got "
                        "updated, will check on next run", lbl)
            continue
        lbl = "%s [%s]" % (lbl, condition)
        target = old_targets.get(condition.metric, condition.metric)
        ## if "%(head)s." not in target:
            ## target = "%(head)s." + target
        if condition.operator not in ('gt', 'lt'):
            log.error("%s unknown operator '%s'",
                      lbl, condition.operator)
            continue
        if not condition.aggregate:
            log.warning("%s setting aggregate to 'all'", lbl)
            condition.aggregate = 'all'
            condition.save()
        if condition.aggregate not in ('all', 'any', 'avg'):
            log.error("%s unknown aggregate '%s'", lbl, condition.aggregate)
            continue
        if condition.active_after > time():
            log.info("%s not yet active", lbl)
            continue
        if target not in conditions:
            conditions[target] = [condition]
        else:
            conditions[target].append(condition)
    if not conditions:
        log.warning("%s no rules found", machine.uuid)
        return

    try:
        data = handler.get_data(conditions.keys(), start='-90sec')
    except GraphiteError as exc:
        log.warning("%s error fetching stats %r", machine.uuid, exc)
        return

    # check all conditions
    for item in data:
        target = item['_requested_target']
        if target not in conditions:
            log.warning("%s get data returned unexpected target %s",
                        machine.uuid, target)
            continue
        datapoints = [(val, ts) for val, ts in item['datapoints']
                      if val is not None]
        for condition in conditions.pop(target):
            if not datapoints:
                log.warning("%s no data for rule", machine.uuid)
                continue
            check_condition(condition, datapoints)

    if conditions:
        for target, condition in conditions.items():
            if target == "nodata":
                # if nodata rule didn't return any datapoints, the whisper
                # files must be missing, so make the rule true
                check_condition(condition, [(1, 0)])
            else:
                log.warning("%s/%s [%s] target not found for rule",
                            machine.uuid, condition.rule_id, condition)


def main():
    pool = ThreadPool(config.ALERT_THREADS)
    while True:
        t0 = time()
        pool.map(check_machine, get_all_machines())
        t1 = time()
        dt = t1 - t0
        run_msg = "Run completed in %.1f seconds." % dt
        sleep_time = config.ALERT_PERIOD - dt
        if sleep_time > 0:
            log.info("%s Sleeping for %.1f seconds.", run_msg, sleep_time)
            sleep(sleep_time)
        else:
            log.warning("%s Will not sleep because ALERT_PERIOD=%d",
                        run_msg, config.ALERT_PERIOD)
        log.info("=" * 79)


if __name__ == "__main__":
    sleep(10)
    main()
