import logging
import requests
from time import time, sleep


from mist.monitor.model import get_all_machines

from mist.monitor.graphite import SingleGraphiteSeries
from mist.monitor.graphite import CombinedGraphiteSeries
from mist.monitor.graphite import NoDataSeries
from mist.monitor.graphite import CpuUtilSeries
from mist.monitor.graphite import LoadSeries
from mist.monitor.graphite import MemSeries
from mist.monitor.graphite import DiskWriteSeries
from mist.monitor.graphite import NetTxSeries

from mist.monitor.helpers import tdelta_to_str

from mist.monitor.exceptions import ConditionNotFoundError
from mist.monitor.exceptions import GraphiteError

from mist.monitor import config


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
ch = logging.StreamHandler()
log.addHandler(ch)


METRICS_MAP = {
    'nodata': NoDataSeries,
    'cpu': CpuUtilSeries,
    'load': LoadSeries,
    'ram': MemSeries,
    'disk-write': DiskWriteSeries,
    'disk': DiskWriteSeries,  # to gracefully handle old rules (TODO:investigate)
    'network-tx': NetTxSeries,
}


def gt(series, threshold):
    value = min([value for timestamp, value in series])
    return value > threshold, value


def lt(series, threshold):
    value = max([value for timestamp, value in series])
    return value < threshold, value


OPERATORS_MAP = {
    'gt': gt,
    'lt': lt,
}


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
    try:
        resp = requests.put(config.CORE_URI + "/rules", params=params,
                            verify=config.SSL_VERIFY)
    except Exception as exc:
        log.error("Error sending notification to core: %r", exc)
        return False
    if not resp.ok:
        log.error("Error sending notification to core: %s", resp.text)
        return False
    return True


def check_condition(condition, series):

    # extract value from series and apply operator
    operator = OPERATORS_MAP[condition.operator]
    triggered, value = operator(series, condition.value)

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
    log.info("  * rule '%s' (%s):%s since %s (value=%s, level=%d)",
             condition.rule_id, condition, condition.state, since_str,
             value, condition.notification_level)

    # notify core if necessary
    reminder_list = condition.reminder_list or config.REMINDER_LIST
    if condition.state and len(reminder_list) > condition.notification_level:
        duration = time() - condition.state_since
        next_notification = reminder_list[condition.notification_level]
        if duration >= next_notification:
            log.info("    * sending WARNING to core")
            if not notify_core(condition, value):
                # don't advance notification level if notification failed
                return
            condition.notification_level += 1
            condition.save()
    elif not condition.state and not condition.notification_level:
        log.info("    * sending OK to core")
        if not notify_core(condition, value):
            # don't advance notification level if notification failed
            return
        condition.notification_level = 1
        condition.save()


def check_machine(machine, rule_id=''):
    """Check all conditions for given machine with a single graphite query.

    If rule is specified, on that rule will be checked.

    """

    log.info("Checking machine '%s':", machine.uuid)

    # check if machine activated
    if not machine.activated:
        log.info("  * Machine is not yet activated (inactive for %s).",
                 tdelta_to_str(time()-machine.enabled_time))
        nodata_series = NoDataSeries(machine.uuid)
        if nodata_series.check_head(bucky=config.ALERTS_BUCKY):
            log.info("  * Machine just got activated!")
            with machine.lock_n_load():
                machine.activated = True
                machine.save()
                for rule_id in machine.rules:
                    condition = machine.get_condition(rule_id)
                    condition.active_after = time() + 30
                    condition.save()
        return

    # gather all conditions
    conditions = []
    rules = [rule_id] if rule_id else machine.rules
    for rule_id in rules:
        try:
            condition = machine.get_condition(rule_id)
        except ConditionNotFoundError:
            log.warning("  * rule '%s':Condition not found, probably rule just"
                        " got updated. Will check on next run.", rule_id)
            continue
        if condition.metric not in METRICS_MAP:
            log.error("  * rule '%s' (%s):Unknown metric '%s'.",
                      rule_id, condition, condition.metric)
            continue
        if condition.operator not in OPERATORS_MAP:
            log.error("  * rule '%s' (%s):Unknown operator '%s'.",
                      rule_id, condition, condition.operator)
            continue
        if condition.active_after > time():
            log.info("  * rule '%s' (%s):Not yet active.", rule_id, condition)
            continue
        conditions.append(condition)
    if not conditions:
        return

    # combine all conditions to perform only one graphite query per machine
    conditions_series = {
        condition.cond_id: METRICS_MAP[condition.metric](machine.uuid)
        for condition in conditions
    }
    combined_series = CombinedGraphiteSeries(machine.uuid,
                                             conditions_series.values())
    try:
        data = combined_series.get_series("-1min")  #(int(time() - 70))
    except GraphiteError as exc:
        log.warning("%r", exc)
        return

    # check all conditions
    for condition in conditions:
        condition_series = data[conditions_series[condition.cond_id].alias]
        if not condition_series:
            log.warning("  * rule '%s' (%s):No data for rule.",
                        condition.rule_id, condition)
            continue
        check_condition(condition, condition_series)


def main():
    while True:
        t0 = time()
        for machine in get_all_machines():
            check_machine(machine)
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
