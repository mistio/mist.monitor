import os

from logging import getLogger

from subprocess import call
import math

import requests

from pyramid.view import view_config
from pyramid.response import Response

from random import gauss

from time import time

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
        f = open("conf/collectd.conf",'w')
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
