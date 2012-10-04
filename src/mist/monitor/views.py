import os
import requests
from subprocess import call
from datetime import datetime
from time import time

import math
from random import gauss
from operator import *

from logging import getLogger

from pyramid.view import view_config
from pyramid.response import Response

from pymongo import Connection
import pymongo

from mist.monitor.config import MONGODB


log = getLogger('mist.core')

@view_config(route_name='machines', request_method='GET', renderer='json')
def list_machines(request):
    file = open(os.getcwd()+'/conf/collectd.passwd')
    machines = file.read().split('\n')
    return machines


@view_config(route_name='machines', request_method='PUT', renderer='json')
def add_machine(request):
    """ add machine to monitored list """

    # get request params
    uuid = request.params.get('uuid', None)
    passwd = request.params.get('passwd', None)

    # check for errors
    if not uuid or not passwd:
        return Response('Unauthorized', 401)

    # check if uuid already in pass file
    try:
        f = open("conf/collectd.passwd")
        res = f.read()
        f.close()
        if uuid in res:
            return Response('Conflict', 409)

        # append collectd pw file
        f = open("conf/collectd.passwd", 'a')
        f.writelines(['\n'+ uuid + ': ' + passwd])
        f.close()
    except Exception as e:
        log.error('Error opening machines pw file: %s' % e)
        return Response('Service unavailable', 503)

    # create new collectd conf section for allowing machine stats
    config_append = """
        PreCacheChain "%sRule"
        <Chain "%sRule">
            <Rule "rule">
                <Match "regex">
                    Host "^%s$"
                </Match>
                Target return
            </Rule>
            Target stop
        </Chain>""" % (uuid, uuid, uuid)

    try:
        f = open("conf/collectd_%s.conf"%uuid,"w")
        f.write(config_append)
        f.close()

        # include the new file in the main config
        config_include = "conf/collectd_%s.conf" % uuid
        f = open("conf/collectd.conf.local", "a")
        f.write('\nInclude "%s"\n'% config_include)
        f.close()
    except Exception as e:
        log.error('Error opening collectd conf files: %s' % e)
        return Response('Service unavailable', 503)

    try:
        call(['/usr/bin/pkill','-HUP','collectd'])
    except Exception as e:
        log.error('Error restarting collectd: %s' % e)

    return {}


@view_config(route_name='machine', request_method='DELETE', renderer='json')
def remove_machine(request):
    """ remove machine from monitored list """
    # get request params
    try:
        uuid = request.matchdict['machine']

        # check for errors
        if not uuid:
            raise
    except Exception as e:
        return Response('Bad Request', 400)

    try:
        f = open("conf/collectd.passwd")
        res = f.read()
        f.close()
        if uuid not in res:
           return Response('Not Found', 404)
        lines = res.split('\n')
        for l in lines:
            if uuid in l:
                lines.remove(l)
        res = '\n' .join(lines)
        f = open("conf/collectd.passwd",'w')
        f.write(res)
        f.close()
    except Exception as e:
        log.error('Error opening machines pw file: %s' % e)
        return Response('Service unavailable', 503)

    try:
        f = open("conf/collectd.conf.local")
        res = f.read()
        f.close()
        if uuid not in res:
           return Response('Not Found', 404)
        lines = res.split('\n')
        for l in lines:
            if uuid in l:
                lines.remove(l)
        res = '\n' .join(lines)
        f = open("conf/collectd.conf.local",'w')
        f.write(res)
        f.close()
    except Exception as e:
        log.error('Error opening collectd conf file: %s' % e)
        return Response('Service unavailable', 503)


@view_config(route_name='teststats', request_method='GET', renderer='json')
def get_teststats(request):
    """Get all stats for this machine, the client will draw them

    TODO: return real values
    WARNING: copied from mist.core
    """
    interval = 5000 # in milliseconds
    timestamp = time() * 1000 # from seconds to milliseconds
    # check if you just need an update or the full list
    changes_since = request.GET.get('changes_since', None)

    if changes_since:
        # how many samples were created in this interval
        samples = timestamp - float(changes_since)
        samples = math.floor(samples / interval)
        samples = int(samples)
    else:
        # set maximum number of samples
        samples = 1000

    cpu = []
    load = []
    memory = []
    disk = []

    for i in range(0, samples):
        cpu.append(abs(gauss(70.0, 5.0)))
        load.append(abs(gauss(4.0, 0.02)))
        memory.append(abs(gauss(4000.0, 10.00)))
        disk.append(abs(gauss(40.0, 3.0)))

    ret = {'timestamp': timestamp,
           'interval': interval,
           'cpu': cpu,
           'load': load,
           'memory': memory,
           'disk': disk}

    return ret


@view_config(route_name='mongostats', request_method='GET', renderer='json')
def get_mongostats(request):
    """Get stats for this machine using the mongodb backend. Data is stored using a
    different format than the other get_stats functions, following the targets template
    below

    FIXME: We get a float division error sometimes. This may be due to our total_diff
    array handling or something else. We need to figure this out ASAP.
    """

    mongodb_hostname = MONGODB['host']
    mongodb_port = MONGODB['port']
    mongodb_name = MONGODB['dbname']
    # get request params
    try:
        uuid = request.matchdict['machine']

        # check for errors
        if not uuid:
            log.error("cannot find uuid %s" % uuid)
            raise
    except Exception as e:
        return Response('Bad Request', 400)

    expression = request.params.get('expression', ['cpu', 'load', 'memory', 'disk'])
    stop = int(request.params.get('stop', int(time())))
    step = int(request.params.get('step', 60000))
    start = int(request.params.get('start', stop - step))

    if not expression:
        expression = targets.keys()

    connection = Connection(mongodb_hostname, mongodb_port)
    db = connection[mongodb_name]
    step = int(step/1000)
    no_values_asked = int((stop - start)/step)

    ret = { }

    if expression.__class__ in [str,unicode]:
        expression = [expression]

    for col in expression:
        res = {}

        ret[col] = {'total': [],'util': [],'total_diff':[] ,'used_diff': [] ,
                    'used' : [] }

        query_dict = {'host': uuid,
                      'time': {"$gte": datetime.fromtimestamp(int(start)),
                               "$lt": datetime.fromtimestamp(int(stop)) }}

        #XXX: No need to use limit, we just return all values in the requested time range
        res = db[col].find(query_dict).sort('time', pymongo.DESCENDING)
        #.limit(2*8*(int((stop-start)/step)))

        prev = None
        set_of_cpus = []
        for r in res:
            curr = r['time']
            index = r['type_instance']
            value = r['values']
            cpu_no = r['plugin_instance']
            if not ret[col].get(index, None):
                ret[col][index] = value
            else:
                ret[col][index].extend(value)

            if cpu_no not in set_of_cpus:
                set_of_cpus.append(cpu_no)

            if prev != curr:
                ret[col]['total'].append(0)
                ret[col]['used'].append(0)

            if index != 'idle':
                ret[col]['used'][-1] += float(value[0])
            ret[col]['total'][-1] += value[0]
            prev = curr

        for j in range(1, len(ret[col]['total'])):
            i = len(ret[col]['total']) -1 - j
            ret[col]['total_diff'].append  (abs(ret[col]['total'][i-1] - ret[col]['total'][i]))
            ret[col]['used_diff'].append(abs(ret[col]['used'][i-1] - ret[col]['used'][i]))
        #FIXME: the way we calculate CPU util leaves us with N-1 values to return to D3
        #Thus, we can cheat (if step is 1, we would be left with 0 values for util.
        #ret[col]['total_diff'].append(ret[col]['total_diff'][-1])
        #ret[col]['used_diff'].append(ret[col]['used_diff'][-1])

        ret[col]['util'] = map(div, ret[col]['used_diff'], ret[col]['total_diff'])
        util_values = len(ret[col]['util'])
        zero_prepend = []
        if util_values < no_values_asked:
            zero_prepend = [0] * (no_values_asked - util_values)
        zero_prepend.extend(ret[col]['util'])

    timestamp = time() * 1000
    ret['timestamp'] = timestamp
    ret['interval'] = step

    ret[col]['util'] = zero_prepend
    #log.info(ret)
    return ret


@view_config(route_name='stats', request_method='GET', renderer='json')
def get_stats(request):
    """Get all stats for this machine, the client will draw them

    """

    #FIXME: default targets -- could be user customizable
    targets = ["cpu", "load", "memory", "disk"]

    # get request params
    try:
        uuid = request.matchdict['machine']

        # check for errors
        if not uuid:
            log.error("cannot find uuid %s" % uuid)
            raise
    except Exception as e:
        return Response('Bad Request', 400)


    changes_since = request.params.get('changes_since', None)
    if not changes_since:
        changes_since = "-1hours&"
    else:
        changes_since = "%d" %(int(float(changes_since)/1000))

    data_format = request.params.get('format', None)
    if not data_format:
        data_format = "format=json&"

    #FIXME: get rid of that, we are already on the monitoring server,
    #we should know better ;-)
    graphite_uri = "http://experiment.unweb.me:8080"

    data = {'cpu': [ ], 'load':  [ ], 'memory': [ ], 'disk': [ ] }
    interval = 1000

    for target in targets:
        target_uri = "target=servers." + uuid + "." + target + "*.*.*&"
        time_range = "from=%s&until=now" %(changes_since)
        #construct uri
        uri = graphite_uri + "/render?" + data_format + target_uri + time_range
        print uri

        r = requests.get(uri)
        if r.status_code == 200:
            log.info("connect OK")
        else:
            log.error("Status code = %d" %(r.status_code))

        if not len(r.json):
            continue

        for i in range (0, len(r.json[0]['datapoints'])):
            value = r.json[0]['datapoints'][i][0]
            if value:
                data[target].append(r.json[0]['datapoints'][i][0])
            else:
                data[target].append(1)

    #timestamp = r.json[0]['datapoints'][0][1] * 1000
    timestamp = time() * 1000

    ret = {'timestamp': timestamp,
           'interval': interval,
           'cpu': data['cpu'],
           'load': data['load'],
           'memory': data['memory'],
           'disk': data['disk']}

    log.info(ret)
    return ret
