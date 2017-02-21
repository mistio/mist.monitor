import os
import re
import logging
from subprocess import call
from time import time

import requests

log = logging.getLogger(__name__)

try:
    import fcntl
    CAN_LOCK = True
except ImportError:
    log.error("Can't import fcntl module, won't lock collectd.passwd")
    CAN_LOCK = False

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
from mist.monitor.exceptions import GraphiteError


def update_collectd_conf():
    """Update collectd.passwd and collectd.conf.local file.

    Reconstructs collectd.passwd adding a uuid/password entry for every machine.

    """

    path = config.AUTH_FILE_PATH
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w') as f:  # write new auth file to temporary file
        if CAN_LOCK:  # disallow concurrent rewrites of authfile
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.writelines(["%s: %s\n" % (machine.uuid, machine.collectd_password)
                      for machine in get_all_machines()])
    os.rename(tmp_path, path)  # move tmp file to authfile location
    os.utime(path, None)  # touch authfile to notify bucky that it changed


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

    # add uuid/passwd in collectd.passwd
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

    # reconstruct collectd passwords file to remove uuid/passwd
    update_collectd_conf()


def add_rule(uuid, rule_id, metric, operator, value,
             aggregate="all", reminder_list=None, reminder_offset=0,
             active_after=30):
    """Add or update a rule."""

    if aggregate not in ('all', 'any', 'avg'):
        raise BadRequestError("Param 'aggregate' must be in "
                              "('all', 'any', 'avg').")
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
    condition.aggregate = aggregate
    condition.value = value
    # reminder_list should be a list of integers (notifications after rule
    # being triggered in seconds). If not provided, default will be used.
    if reminder_list:
        condition.reminder_list = reminder_list
    condition.reminder_offset = reminder_offset
    # we set notification level to 1 so that new rules that are not satisfied
    # don't send an OK to core immediately after creation
    condition.notification_level = 1

    # TODO: verify target is valid

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

    old_targets = {
        'cpu': 'cpu.total.nonidle',
        'load': 'load.shorterm',
        'ram': 'memory.nonfree_percent',
        'disk-read': 'disk.total.disk_octets.read',
        'disk-write': 'disk.total.disk_octets.write',
        'network-rx': 'interface.total.if_octets.rx',
        'network-tx': 'interface.total.if_octets.tx',
    }
    targets = [old_targets.get(metric, metric) for metric in metrics]
    handler = graphite.MultiHandler(uuid)
    data = handler.get_data(targets, start, stop, interval_str=interval_str)
    for item in data:
        if item['alias'].rfind("%(head)s.") == 0:
            item['alias'] = item['alias'][9:]
    return data


def get_multi(target, start="", stop="", interval_str=""):
    if interval_str:
        target = graphite.summarize(target, interval_str)
    params = [('target', target),
              ('from', start or None),
              ('until', stop or None),
              ('format', 'json')]
    resp = requests.get('%s/render' % config.GRAPHITE_URI, params=params)
    if not resp.ok:
        log.error(resp.text)
        raise GraphiteError(str(resp))
    return resp.json()


def get_load(uuids, start="", stop="", interval_str=""):
    data = get_multi('bucky.{%s}.load.shortterm' % (','.join(uuids), ),
                     start, stop, interval_str)
    ret = {}
    for item in data:
        uuid = item['target'].split('.')[1]
        item['name'] = uuid
        ret[uuid] = item
    return ret


def get_cores(uuids, start="", stop="", interval_str=""):
    target = 'groupByNode(bucky.{%s}.cpu.*.system,1,"countSeries")' % (
        ','.join(uuids), )
    data = get_multi(target, start, stop, interval_str)
    ret = {}
    for item in data:
        uuid = item['target']
        item['name'] = uuid
        ret[uuid] = item
    return ret


def find_metrics(uuid):
    handler = graphite.MultiHandler(uuid)
    metrics = handler.find_metrics()
    for item in metrics:
        if item['alias'].rfind("%(head)s.") == 0:
            item['alias'] = item['alias'][9:]
    return metrics


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
                aggregate=rule_dict.get('aggregate'),
                reminder_list=rule_dict.get('reminder_list'),
                reminder_offset=rule_dict.get('reminder_offset', 0),
            )

    # update collectd's conf and reload it
    update_collectd_conf()
