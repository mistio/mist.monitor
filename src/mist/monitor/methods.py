import os
import logging
from subprocess import call
from time import time

## from mist.monitor.stats import mongo_get_stats
## from mist.monitor.stats import graphite_get_stats, graphite_get_loadavg
## from mist.monitor.stats import dummy_get_stats
## from mist.monitor.rules import add_rule
## from mist.monitor.rules import remove_rule

from mist.monitor.model import Machine, Condition
from mist.monitor.model import get_machine_from_uuid
from mist.monitor.model import get_condition_from_cond_id
from mist.monitor.model import get_all_machines

from mist.monitor.exceptions import RequiredParameterMissingError
from mist.monitor.exceptions import MachineNotFoundError
from mist.monitor.exceptions import RuleNotFoundError
from mist.monitor.exceptions import MachineExistsError


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


def add_machine(uuid, password):
    """Adds machine to monitored list and inform collectd of new machine."""

    if not uuid:
        raise RequiredParameterMissingError("uuid")
    if not password:
        raise RequiredParameterMissingError("password")

    machine = get_machine_from_uuid(uuid)
    if machine:
        raise MachineExistsError(uuid)

    machine = Machine()
    machine.uuid = uuid
    machine.collectd_password = password
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
    with open(rule_file_path, "w") as f:
        f.write(chain_rule)

    # add uuid/passwd in collectd conf and import chain rule
    update_collectd_conf()


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


def update_rule(uuid, rule_id, metric, operator, value, time_to_wait):
    """Add or edit a rule."""

    machine = machine_from_uuid(uuid)
    if not machine:
        raise MachineNotFoundError(uuid)

    # create new condition
    condition = Condition()
    condition.uuid = uuid
    condition.rule_id = rule_id
    condition.metric = metric
    condition.operator = operator
    condition.value = value
    condition.time_to_wait = time_to_wait
    condition.cond_id = get_rand_id()
    condition.create()

    with machine.lock_n_load():
        # if rule doesn't exist, create it
        if rule_id not in machine.rules:
            rule = Rule()
            machine.rules[rule_id] = rule
        rule = machine.rules[rule_id]
        # if rule had an associated condition, remove it
        if rule.warning:
            old_condition = machine.get_condition(rule.warning)
            old_condition.remove()
        # associate new condition with rule
        rule.warning = condition.cond_id
        machine.save()


def remove_rule(uuid, rule_id):
    """Remove a rule from a machine (along with its associated condition)."""

    machine = machine_from_uuid(uuid)
    if not machine:
        raise MachineNotFoundError(uuid)
    with machine.lock_n_load():
        if not rule_id in machine.rules:
            raise RuleNotFoundError(rule_id)

        # delete associated condition
        condition = machine.get_condition(rule_id)
        condition.remove()

        # delete rule
        del machine.rules[rule_id]
        machine.save()


def get_stats(request):
    """
    Returns all stats for a machine, the client will draw them.
    """
    uuid = request.matchdict['machine']

    if not uuid:
        log.error("cannot find uuid %s" % uuid)
        return Response('Bad Request', 400)

    allowed_expression = ['cpu', 'load', 'memory', 'disk', 'network']

    expression = request.params.get('expression',
                                    ['cpu', 'load', 'memory', 'disk', 'network'])
    if expression.__class__ in [str,unicode]:
        #expression = [expression]
        expression = expression.split(',')

    for target in expression:
        if target not in allowed_expression:
            log.error("expression error '%s'" % target)
            return Response('Bad Request', 400)

    # step comes from the client in millisecs, convert it to secs
    step = int(request.params.get('step', 10000))
    if (step >= 5000):
        step = int(step/1000)
    elif step == 0:
        log.warn("We got step == 0, maybe the client is broken ;S, using default")
        step = 60
    else:
        log.warn("We got step < 1000, maybe the client meant seconds ;-)")

    stop = int(request.params.get('stop', int(time())))
    start = int(request.params.get('start', stop - step))

    stats = {}
    backend = request.registry.settings['backend']
    if backend['type'] == 'graphite':
        host = backend['host']
        port = backend['port']
        stats = graphite_get_stats(host, port, uuid, expression, start, stop, step)
    elif backend['type'] == 'dummy':
        stats = dummy_get_stats(expression, start, stop, step)
    else:
        log.error('Requested invalid monitoring backend: %s' % backend)
        return Response('Service unavailable', 503)

    return stats
