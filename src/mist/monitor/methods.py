import os
import re
import logging
from subprocess import call
from time import time

from mist.monitor import config
from mist.monitor import graphite

from mist.monitor.helpers import get_rand_token

from mist.monitor.model import Machine, Condition, Rule
from mist.monitor.model import get_machine_from_uuid
from mist.monitor.model import get_condition_from_cond_id
from mist.monitor.model import get_all_machines

from mist.monitor.exceptions import RequiredParameterMissingError
from mist.monitor.exceptions import MachineNotFoundError
from mist.monitor.exceptions import RuleNotFoundError
from mist.monitor.exceptions import MachineExistsError
from mist.monitor.exceptions import BadRequestError


log = logging.getLogger(__name__)


def update_collectd_conf():
    """Update collectd.passwd and collectd.conf.local file.

    Reconstructs collectd.passwd adding a uuid/password entry for every machine.
    Reconstructs collectd.conf.local adding an Import statement for every
    machine.
    Sends a SIGHUP to collectd to load fresh configuration.

    """

    lines = ["%s: %s\n" % (machine.uuid, machine.collectd_password)
             for machine in get_all_machines()]
    with open(os.getcwd() + "/conf/collectd.passwd", "w") as f:
        f.writelines(lines)

    import_lines = []
    passwd_lines = []
    for machine in get_all_machines():
        rule_filepath = os.getcwd() + "/conf/collectd_%s.conf" % machine.uuid
        import_lines.append('Include "%s"\n' % rule_filepath)
        passwd_lines.append("%s: %s\n" % (machine.uuid,
                                          machine.collectd_password))

    passwd_filepath = os.getcwd() + "/conf/collectd.passwd"
    with open(passwd_filepath + ".tmp", "w") as f:
        f.writelines(passwd_lines)
    os.rename(passwd_filepath + ".tmp", passwd_filepath)

    imports_filepath = os.getcwd() + "/conf/collectd.conf.local"
    with open(imports_filepath + ".tmp", "w") as f:
        f.writelines(import_lines)
    os.rename(imports_filepath + ".tmp", imports_filepath)

    # send a SIGHUP to collectd to reload configuration."""
    call(['/usr/bin/pkill', '-HUP', 'collectd'])


def add_machine(uuid, password, update_collectd=True):
    """Adds machine to monitored list and inform collectd of new machine."""

    if not uuid:
        raise RequiredParameterMissingError("uuid")
    if not password:
        raise RequiredParameterMissingError("password")

    machine = get_machine_from_uuid(uuid)
    if machine:
        ## raise MachineExistsError(uuid)
        with machine.lock_n_load():
            machine.collectd_password = password
            machine.enabled_time = time()
            machine.save()
    else:
        machine = Machine()
        machine.uuid = uuid
        machine.collectd_password = password
        machine.enabled_time = time()
        machine.create()

    # Create new collectd conf to make collectd only accept data for a certain
    # machine from requests coming from the machine with the right uuid.
    chain_rule = """PreCacheChain "%(uuid)sRule"
    <Chain "%(uuid)sRule">
        <Rule "rule">
            <Match "regex">
                Host "^%(uuid)s$"
            </Match>
            Target return
        </Rule>
        Target continue
    </Chain>
    """ % {'uuid': uuid}
    rule_filepath = os.getcwd() + "/conf/collectd_%s.conf" % machine.uuid
    with open(rule_filepath, "w") as f:
        f.write(chain_rule)

    # add uuid/passwd in collectd conf and import chain rule
    if update_collectd:
        update_collectd_conf()

    # add no-data rule
    add_rule(machine.uuid, 'nodata', 'nodata', 'gt', 0)


def remove_machine(uuid):
    """Removes a machine from monitored list and from collectd's conf files."""

    if not uuid:
        raise RequiredParameterMissingError("uuid")

    machine = get_machine_from_uuid(uuid)
    if not machine:
        raise MachineNotFoundError(uuid)

    for rule_id in machine.rules:
        try:
            remove_rule(uuid, rule_id)
        except:
            log.error("Error removing rule '%s'.", rule_id)

    machine.delete()

    # Remove chain rule file.
    os.remove(os.getcwd() + "/conf/collectd_%s.conf" % machine.uuid)

    # reconstruct collectd passwords file to remove uuid/passwd and import
    update_collectd_conf()


def add_rule(uuid, rule_id, metric, operator, value, reminder_list=None,
             active_after=30):
    """Add or update a rule."""

    machine = get_machine_from_uuid(uuid)
    if not machine:
        raise MachineNotFoundError(uuid)

    # create new condition
    condition = Condition()
    condition.uuid = uuid
    condition.rule_id = rule_id
    condition.cond_id = get_rand_token()
    condition.active_after = time() + active_after
    condition.metric = metric
    condition.operator = operator
    condition.value = value
    # reminder_list should be a list of integers (notifications after rule
    # being triggered in seconds). If not provided, default will be used.
    if reminder_list:
        condition.reminder_list = reminder_list
    # we set not level to 1 so that new rules that are not satisfied
    # don't send an OK to core immediately after creation
    condition.notification_level = 1
    condition.create()

    with machine.lock_n_load():
        # if rule doesn't exist, create it
        if rule_id not in machine.rules:
            rule = Rule()
            machine.rules[rule_id] = rule
        rule = machine.rules[rule_id]
        # if rule had an associated condition, remove it
        if rule.warning:
            old_condition = machine.get_condition(rule_id)
            old_condition.delete()
        # associate new condition with rule
        rule.warning = condition.cond_id
        machine.save()


def remove_rule(uuid, rule_id):
    """Remove a rule from a machine (along with its associated condition)."""

    machine = get_machine_from_uuid(uuid)
    if not machine:
        raise MachineNotFoundError(uuid)
    with machine.lock_n_load():
        if not rule_id in machine.rules:
            raise RuleNotFoundError(rule_id)

        # delete associated condition
        condition = machine.get_condition(rule_id)
        condition.delete()

        # delete rule
        del machine.rules[rule_id]
        machine.save()


def get_stats(uuid, metrics, start="", stop="", interval_str=""):
    builtin_targets = {
        'cpu': graphite.CpuUtilSeries,
        'load': graphite.LoadSeries,
        'ram': graphite.MemSeries,
        'disk-read': graphite.DiskAllReadSeries,
        'disk-write': graphite.DiskAllWriteSeries,
        'network-rx': graphite.NetEthRxSeries,
        'network-tx': graphite.NetEthTxSeries,
    }
    series_list = []
    for metric in metrics or builtin_targets.keys():
        if metric in builtin_targets:
            series_list.append(builtin_targets[metric](uuid))
        else:
            if "%(head)s" in metric:
                series_list.append(
                    graphite.CustomSingleGraphiteSeries(uuid, target=metric)
                )
            else:
                raise BadRequestError("metric '%s' not allowed" % metric)
    series = graphite.CombinedGraphiteSeries(uuid, series_list=series_list)
    return series.get_series(start, stop, interval_str=interval_str)


def find_metrics(uuid):
    series = graphite.LoadSeries(uuid)
    return series.find_metrics(strip_head=True)


def reset_hard(data):
    """Reset mist.monitor data.

    This will erase all previous data, save the supplied data and restart
    collectd. It will not affect monitoring data, but will reset all machines
    with enabled monitoring, their passwords, rules etc.

    data is expected to be a dict of uuids mapping to machine dicts.
    Each machine needs to have a collectd_password key.
    Optionally it can contain a rule_key which should be a dict with rule_id's
    as keys and rule dicts as values. A rule_dict nees to have operator,
    metric, value etc.

    """

    # drop databases
    Machine()._get_mongo_coll().drop()
    Condition()._get_mongo_coll().drop()

    # flush memcache
    Machine()._memcache.flush_all()

    # recreate machines and rules
    for uuid, machine_dict in data.iteritems():
        add_machine(uuid, machine_dict['collectd_password'],
                    update_collectd=False)
        for rule_id, rule_dict in machine_dict.get('rules', {}).iteritems():
            add_rule(
                uuid=uuid,
                rule_id=rule_id,
                metric=rule_dict['metric'],
                operator=rule_dict['operator'],
                value=rule_dict['value'],
                reminder_list=rule_dict.get('reminder_list'),
            )

    # update collectd's conf and reload it
    update_collectd_conf()
