"""Module for setting up alerts

"""
import os

import requests
import yaml

from datetime import datetime

from logging import getLogger

from mist.monitor.stats import graphite_build_cpu_target,      graphite_build_inner_cpu_target
from mist.monitor.stats import graphite_build_mem_target_v2,    graphite_build_inner_mem_target_v2
from mist.monitor.stats import graphite_build_mem_target
from mist.monitor.stats import graphite_build_load_target,      graphite_build_inner_load_target
from mist.monitor.stats import graphite_build_net_target
from mist.monitor.stats import graphite_build_disk_target
from mist.monitor.stats import graphite_build_net_tx_target,    graphite_build_inner_net_tx_target
from mist.monitor.stats import graphite_build_disk_write_target, graphite_build_inner_disk_write_target
from mist.monitor.stats import graphite_build_net_rx_target,    graphite_build_inner_net_rx_target
from mist.monitor.stats import graphite_build_disk_read_target, graphite_build_inner_disk_read_target
from mist.monitor.stats import MACHINE_PREFIX

log = getLogger('mist.monitor')

# We now support network tx/rx and disk rd/wr rules. 
# We just keep network and disk metrics to account 
# for aggregate rules in the future.

metrics = ['cpu',
           'ram',
           'load',
           'disk',
           'network',
           'network-tx',
           'network-rx',
           'disk-read',
           'disk-write',
          ]

REMINDER_LIST = [60, # 1min
                 5 * 60, # 5mins 
                 10 * 60, # 10mins 
                 30 * 60, # 30mins
                 60 * 60, # 1h
                 2 * 3600, # 2h
                 6 * 3600, # 6h
                 10 * 3600, # 10h
                 20 * 3600, # 20h 
                 24 * 3600, # 1d
                ] # 

graphite_url = core_url = ""

settings_template = {'graphite_url': graphite_url, 
                     'core_url': core_url, 
                     'reminder_list': [], 
                     'user': '',
                     'machine_password': '',
                     'pagerduty_key': '', 
                     'hipchat_key':'', 
                     'graphite_auth_user': '', 
                     'graphite_auth_password': ''
                    }

alert_template = {'check_method': '', 
                  'from': '', 
                  'name': '', 
                  'time_to_wait': 60, 
                  'notifiers': [], 
                  'target': '', 
                  'rules': [] 
                 }

op_func = {'gt': 'greater than', 'lt': 'less than'}


def build_alert_target(uuid, metric):
    """
    """

    switch_stat = {'cpu': graphite_build_inner_cpu_target,
                   'ram': graphite_build_inner_mem_target_v2, 
                   'load': graphite_build_inner_load_target,
                   'network': graphite_build_net_target,
                   'network-tx': graphite_build_inner_net_tx_target,
                   'network-rx': graphite_build_inner_net_rx_target,
                   'disk': graphite_build_disk_target,
                   'disk-read': graphite_build_inner_disk_read_target,
                   'disk-write': graphite_build_inner_disk_write_target,
                  }

    if metric not in metrics:
        log.error("%s not found in %s" % (metric, metrics))
        return 1

    target = switch_stat[metric](uuid)
    ret_target = target.replace('target=','')
    ret_target = "alias(%s, '%s')" % (ret_target, metric)

    return ret_target
    

def update_alert(alerts, rule_id, alert_target, metric, operator, value, time_to_wait):
    """
    """

    for alert in alerts:
        if rule_id not in alert['name']:
            log.debug("not found, continuing")
            continue
        log.debug("found, alert, rule_id = %s, alert = %s" % (rule_id, alert))
        if alert_target != alert.get('target', None):
            log.debug("changing target from %s to %s" % (alert['target'], alert_target))
            alert['target'] = alert_target
        rules = alert['rules']
        if not rules:
            log.debug("Something terrible has happened, no rules available")
        log.debug("rules = %s" % rules)
        if 'cpu' in alert_target:
            #print "orig value %d" % value
            value = float(value)/100
            #print "value %f" % value
        condition = "%s %s" % (op_func[operator], value)
        log.debug(condition)
        rule = { str(condition).encode('ascii', 'ignore'): "critical" }
        log.debug(rule)
        #if len(rules):
        #    log.debug("rules length is %d" % len(rules))
        #    for r in rules:
        #        log.debug("looping around rules: %s" % r)
        #        if op_func[operator] in r.keys()[0]:
        #            log.debug("found a similar one")
        #            rules[rules.index(r)] = rule
        #            log.debug("replacing the rule")
        #            return 0
        #    log.debug("didn't find a similar one, appending to the list")
        #    rules.append(rule)
        #    log.debug(rules)
        #    return 0
        #else:
        log.debug("rule list empty, adding ours")
        alert['rules'] = [rule]
        return 0

    return 1

    
def add_alert(alerts, rule_id, alert_target, metric, operator, value, time_to_wait):
    """
    """

    alert = alert_template
    alert['check_method'] = 'average'
    alert['from'] = '-5mins'
    alert['time_to_wait'] = time_to_wait
    #alert['name'] = "%s-%s" % (metric, rule_id)
    alert['name'] = "%s" % rule_id
    alert['name'] = str(alert['name']).encode('ascii', 'ignore')
    alert['notifiers'] = ['mail']
    alert['target'] = str(alert_target).encode('ascii', 'ignore')
    if 'cpu' in alert_target:
        #print "orig value %s" % value
        value = float(value)/100
        #print "value %f" % value
    condition = "%s %s" % (op_func[operator], value)
    rule = { str(condition).encode('ascii', 'ignore'): "critical" }
    alert['rules'] = [rule]
    alerts.append(alert)

    return 0


def update_alerts(alerts, params):
    """
    """

    machine_uuid = params.get('uuid', None)
    metric = params.get('metric', None)
    value = params.get('value', None)
    rule_id = params.get('rule_id', None)
    operator = params.get('operator', None)
    time_to_wait = params.get('time_to_wait', 60)
    alert_target = build_alert_target(machine_uuid, metric)
    alert_target = str(alert_target).encode('ascii', 'ignore')
    
    if not alerts:
        alerts = []
        ret = add_alert(alerts, rule_id, alert_target, metric, operator, value, time_to_wait)
        log.error("returning alerts %s" % alerts)
        return alerts

    ret = update_alert(alerts, rule_id, alert_target, metric, operator, value, time_to_wait)
    if not ret:
        log.info("alert updated successfully")
    else:
        log.error("alert not found, will create a new one")
        ret = add_alert(alerts, rule_id, alert_target, metric, operator, value, time_to_wait)

    return alerts


def add_rule(json_rule):
    """
    """

    params = json_rule
    host = params.get('host', None)
    port = params.get('port', None)
    backend_id = params.get('backend_id', None)
    machine_id = params.get('machine_id', None)
    machine_uuid = params.get('uuid', None)
    machine_password = params.get('machine_password', None)
    reminder_list = params.get('reminder_list', REMINDER_LIST)
    user_email = params.get('email', None)
    graphite_uri = "http://%s:%d" % (host, port)
    core_host = params.get('core_host', None)
    core_port = params.get('core_port', 0)
    if core_port in [80, 6543]:
        protocol = "http://"
    elif core_port == 443:
        protocol = "https://"
    else:
        log.error("Cannot add core_uri for alerting")
        return 1
    core_uri = "%s%s:%d" % (protocol, core_host, core_port)
    user_email = str(user_email).encode('ascii', 'ignore')
    machine_password = str(machine_password).encode('ascii', 'ignore')
    machine_id = str(machine_id).encode('ascii', 'ignore')
    backend_id = str(backend_id).encode('ascii', 'ignore')
    #FIXME: find a way to get the machine's IP, name and DNS name
    #name = params.get('name', None)
    #dns_name = params.get('dns_name', None)
    #public_ips = params.get('public_ips', [])

    #let's assume this file exists
    filename = "/conf/galerts-%s.yaml" % machine_uuid
    log.debug(filename)
    try:
        f = open(os.getcwd()+filename, 'r')
        ymlfile = yaml.load(f)
        f.close()
        alerts = ymlfile.get('alerts', None)
        settings = ymlfile.get('settings', None)
        alerts = update_alerts(alerts, params)
        ymlfile = {'alerts': alerts, 'settings': settings}
        f = open(os.getcwd()+filename, "w")
        yaml.dump(ymlfile, f, default_flow_style=False, indent=8, explicit_end=None, explicit_start=None, encoding=None)
        f.close()
    except:
        #file does not exist, so, we create it from scratch
        try:
            f = open(os.getcwd()+filename, 'a')
            settings = settings_template
            alerts = []
            settings['machine_password'] = '%s' % machine_password 
            settings['graphite_url'] = '%s' % graphite_uri
            settings['core_url'] = '%s' % core_uri
            settings['user'] = '%s' % user_email
            settings['reminder_list'] = reminder_list 
            settings['machine_id'] = machine_id
            settings['backend_id'] = backend_id 
            #print settings
            #print reminder_list
            #FIXME: find a way to get the machine's IP, name and DNS name (see above)
            #if public_ips:
            #    settings['public_ips'] = public_ips
            #if dns_name:
            #    settings['dns_name'] = dns_name.encode('ascii', 'ignore')
            #if name:
            #    settings['name'] = name.encode('ascii', 'ignore')
            alerts = update_alerts(alerts, params)
            ymlfile = {'settings': settings, 'alerts': alerts}
            yaml.dump(ymlfile, f, default_flow_style=False, indent=8, explicit_end=None, explicit_start=None, encoding=None)
            f.close()
        except Exception as e:
            log.error("Cannot create alert file for machine %s, %s" % (machine_uuid, e))
            return 1
        
    return 0


def remove_alert(alerts, params):
    """
    """

    machine_uuid = params.get('uuid', None)
    metric = params.get('metric', None)
    value = params.get('value', None)
    rule_id = params.get('rule_id', None)
    operator = params.get('operator', None)

    alert_target = build_alert_target(machine_uuid, metric)
    alert_target = str(alert_target).encode('ascii', 'ignore')

    for alert in alerts:
        if rule_id not in alert['name']:
            log.debug("not found, continuing")
            continue
        log.debug("found, alert, rule_id = %s, alert = %s" % (rule_id, alert))
        alerts.remove(alert)

    return alerts


def remove_rule(request):
    """
    """

    params = request
    machine_uuid = params.get('uuid', None)
    rule_id = params.get('rule_id', None)

    filename = "/conf/galerts-%s.yaml" % machine_uuid
    log.debug(filename)

    try:
        f = open(os.getcwd()+filename, 'r')
        ymlfile = yaml.load(f)
        f.close()
        alerts = ymlfile.get('alerts', None)
        settings = ymlfile.get('settings', None)
        alerts = remove_alert(alerts, params)
        ymlfile = {'alerts': alerts, 'settings': settings}
        #print len(alerts)
        if len(alerts) == 1:
            os.remove(os.getcwd()+filename)
        f = open(os.getcwd()+filename, "w")
        yaml.dump(ymlfile, f, default_flow_style=False, indent=8, explicit_end=None, explicit_start=None, encoding=None)
        f.close()
    except Exception as e:
        log.error("Cannot find alert file for machine %s, %s" % (machine_uuid, e))
        return 1
 
    return 0
