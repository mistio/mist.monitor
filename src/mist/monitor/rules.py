"""Module for setting up alerts

"""
import os

import requests
import yaml

from datetime import datetime

from logging import getLogger

from mist.monitor.stats import graphite_build_cpu_target
from mist.monitor.stats import graphite_build_mem_target
from mist.monitor.stats import graphite_build_load_target
from mist.monitor.stats import graphite_build_net_target
from mist.monitor.stats import graphite_build_disk_target

log = getLogger('mist.monitor')

metrics = ['cpu', 'memory', 'load', 'disk', 'network']

graphite_url = redis_url = ''

settings_template = {'graphite_url': graphite_url, 
                     'redis_url': redis_url, 
                     'pagerduty_key': '', 
                     'hipchat_key':'', 
                     'graphite_auth_user': '', 
                     'graphite_auth_password': ''
                    }

alert_template = {'check_method': '', 
                  'from': '', 
                  'name': '', 
                  'notifiers': [], 
                  'target': '', 
                  'rules': [] 
                 }

op_func = {'gt': 'greater than', 'lt': 'less than'}

def build_alert_target(uuid, metric):
    """
    """

    switch_stat = {'cpu': graphite_build_cpu_target,
                   'memory': graphite_build_mem_target,
                   'load': graphite_build_load_target,
                   'network': graphite_build_net_target,
                   'disk': graphite_build_disk_target 
                  }

    if metric not in metrics:
        return 1

    target = switch_stat[metric](uuid)
    ret_target = target.replace('target=','')

    return ret_target
    
def update_alert(alerts, rule_id, alert_target, metric, operator, value):
    """
    """

    for alert in alerts:
        if rule_id not in alert['name']:
            log.debug("not found, continuing")
            continue
        log.debug("found, alert, rule_id = %s, alert = %s" % (rule_id, alert))
        rules = alert['rules']
        if not rules:
            log.debug("Something terrible has happened, no rules available")
        log.debug("rules = %s" % rules)
        condition = op_func[operator] + " " + value
        log.debug(condition)
        rule = { condition.encode('ascii', 'ignore'): "critical" }
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

    
def add_alert(alerts, rule_id, alert_target, metric, operator, value):
    """
    """

    alert = alert_template
    alert['check_method'] = 'average'
    alert['from'] = '-10mins'
    alert['name'] = "%s-%s" % (metric, rule_id)
    alert['name'] = alert['name'].encode('ascii', 'ignore')
    alert['notifiers'] = ['mail']
    alert['target'] = alert_target.encode('ascii', 'ignore')
    condition = op_func[operator] + " " + value
    print condition
    rule = { condition.encode('ascii', 'ignore'): "critical" }
    print rule
    alert['rules'] = [rule]
    #import pdb;pdb.set_trace()
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
    alert_target = build_alert_target(machine_uuid, metric)
    alert_target = alert_target.encode('ascii', 'ignore')
    
    if not alerts:
        print "alerts list is empty"
        alerts = []
        ret = add_alert(alerts, rule_id, alert_target, metric, operator, value)
        return alerts

    ret = update_alert(alerts, rule_id, alert_target, metric, operator, value)
    if not ret:
        print "alert updated successfully"
    else:
        print "alert not found, will create a new one"
        ret = add_alert(alerts, rule_id, alert_target, metric, operator, value)

    return alerts


def add_rule(json_rule):
    """
    """

    graphite_url = "http://graphite-1-2.mist.io:80"
    redis_url = "redis://localhost:6379"

    params = json_rule
    machine_uuid = params.get('uuid', None)

    #let's assume this file exists
    try:
        f = open(os.getcwd()+"/conf/galerts-" + machine_uuid + ".yaml", 'r')
        ymlfile = yaml.load(f)
        f.close()
        alerts = ymlfile.get('alerts', None)
        settings = ymlfile.get('settings', None)
        alerts = update_alerts(alerts, params)
        ymlfile = {'alerts': alerts, 'settings': settings}
        f = open(os.getcwd()+"/conf/galerts-" + machine_uuid + ".yaml", "w")
        yaml.dump(ymlfile, f, default_flow_style=False, indent=8, explicit_end=None, explicit_start=None, encoding=None)
        f.close()
    except:
        #file does not exist, so, we create it from scratch
        try:
            f = open(os.getcwd()+"/conf/galerts-" + machine_uuid + ".yaml", 'a')
            settings = settings_template
            alerts = []
            graphite_url = 'http://graphite-1-2.mist.io:80'
            redis_url = 'redis://localhost:6379'
            settings['graphite_url'] = graphite_url
            settings['redis_url'] = redis_url
            alerts = update_alerts(alerts, params)
            ymlfile = {'settings': settings, 'alerts': alerts}
            yaml.dump(ymlfile, f, default_flow_style=False, indent=8, explicit_end=None, explicit_start=None, encoding=None)
            f.close()
        except:
            log.error("Cannot create alert file for machine %s" % machine_uuid)
            return 1
        
    return 0


def remove_rule(request):
    """
    """

    return 0
