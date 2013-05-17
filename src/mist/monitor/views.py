import os
from subprocess import call
from time import time

from logging import getLogger

from pyramid.view import view_config
from pyramid.response import Response

from mist.monitor.stats import mongo_get_stats
from mist.monitor.stats import graphite_get_stats
from mist.monitor.stats import dummy_get_stats
from mist.monitor.rules import add_rule
from mist.monitor.rules import remove_rule


log = getLogger('mist.monitor')


@view_config(route_name='machines', request_method='GET', renderer='json')
def list_machines(request):
    """Lists all machines with activated monitoring, for this mist.monitor
    instance.
    """
    file = open(os.getcwd()+'/conf/collectd.passwd')
    machines = file.read().split('\n')

    return machines


@view_config(route_name='machines', request_method='PUT')
def add_machine(request):
    """Adds machine to monitored list."""
    uuid = request.params.get('uuid', None)
    passwd = request.params.get('passwd', None)
    log.debug("Adding machine %s to monitor list" % (uuid))

    if not uuid or not passwd:
        return Response('Unauthorized', 401)

    # check if uuid already in pass file
    try:
        f = open(os.getcwd()+"/conf/collectd.passwd")
        res = f.read()
        f.close()
        if uuid in res:
            return Response('Conflict', 409)

    except Exception as e:
        log.warn('Error opening machines pw file: %s' % e)
        log.warn('Maybe it is our first time here, so we touch the file')

    try:
        # append collectd pw file
        f = open(os.getcwd()+"/conf/collectd.passwd", 'a')
        f.writelines(['\n'+ uuid + ': ' + passwd])
        f.close()
    except Exception as e:
        log.warn('Error creating machines pw file: %s' % e)
        return Response('Service unavailable', 503)

    # create new collectd conf section for allowing machine stats
    config_append = """PreCacheChain "%sRule"
        <Chain "%sRule">
            <Rule "rule">
                <Match "regex">
                    Host "^%s$"
                </Match>
                Target return
            </Rule>
            Target continue
        </Chain>
        """ % (uuid, uuid, uuid)

    try:
        f = open(os.getcwd()+"/conf/collectd_%s.conf"%uuid,"w")
        f.write(config_append)
        f.close()

        # include the new file in the main config
        config_include = os.getcwd()+"/conf/collectd_%s.conf" % uuid
        f = open(os.getcwd()+"/conf/collectd.conf.local", "a")
        f.write('\nInclude "%s"\n'% config_include)
        f.close()
    except Exception as e:
        log.error('Error opening collectd conf files: %s' % e)
        return Response('Service unavailable', 503)

    try:
        call(['/usr/bin/pkill','-HUP','collectd'])
    except Exception as e:
        log.error('Error restarting collectd: %s' % e)

    return Response('Success', 200)


@view_config(route_name='machine', request_method='DELETE')
def remove_machine(request):
    """Removes machine from monitored list."""
    uuid = request.matchdict['machine']
    log.debug("Removing machine %s from monitor list" % (uuid))

    if not uuid:
        return Response('Bad Request', 400)

    try:
        f = open(os.getcwd()+"/conf/collectd.passwd")
        res = f.read()
        f.close()
        if uuid not in res:
           return Response('Not Found', 404)
        lines = res.split('\n')
        for l in lines:
            if uuid in l:
                lines.remove(l)
        res = '\n' .join(lines)
        f = open(os.getcwd()+"/conf/collectd.passwd",'w')
        f.write(res)
        f.close()
    except Exception as e:
        log.error('Error opening machines pw file: %s' % e)
        return Response('Service unavailable', 503)

    try:
        f = open(os.getcwd()+"/conf/collectd.conf.local")
        res = f.read()
        f.close()
        if uuid not in res:
           return Response('Not Found', 404)
        lines = res.split('\n')
        for l in lines:
            if uuid in l:
                lines.remove(l)
        res = '\n' .join(lines)
        f = open(os.getcwd()+"/conf/collectd.conf.local",'w')
        f.write(res)
        f.close()
    except Exception as e:
        log.error('Error opening collectd conf file: %s' % e)
        return Response('Service unavailable', 503)

    return Response('Success', 200)


@view_config(route_name='rules', request_method='PUT', renderer='json')
def update_rules(request):

    try:
        params = request.json_body
        action = params.get('action', None)
        if 'add' in action:
            ret = add_rule(params)
        else:
            ret = remove_rule(params)
        if ret:
            log.error('rule action failed, ret = %d' % ret)
            return Response('Bad Request', 400)
    except:
        return Response('Bad Request', 400)

    log.debug('rule action %s, ret = %d' % (action, ret))
    return Response('Success', 200)


@view_config(route_name='stats', request_method='GET', renderer='json')
def get_stats(request):
    """Returns all stats for a machine, the client will draw them.

    You can configure which monitoring backend to use in mist.io.config. The
    available backends are 'mongodb', 'graphite' and 'dummy'.

    .. warning:: Only mongodb works with the current version of the client
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
    if backend['type'] == 'mongodb':
        stats = mongo_get_stats(backend, uuid, expression, start, stop, step)
    elif backend['type'] == 'graphite':
        host = backend['host']
        port = backend['port']
        stats = graphite_get_stats(host, port, uuid, expression, start, stop, step)
    elif backend['type'] == 'dummy':
        stats = dummy_get_stats(expression, start, stop, step)
    else:
        log.error('Requested invalid monitoring backend: %s' % backend)
        return Response('Service unavailable', 503)

    #log.debug("uuid = %s, expression = %s, start = %d, stop = %d, step = %d" % (uuid, expression, start, stop, step))
    #log.debug(stats)
    return stats
