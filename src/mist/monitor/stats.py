from datetime import datetime
from time import time

from pyramid.response import Response

from logging import getLogger
from logging import WARNING, DEBUG

from pymongo import Connection
from pymongo import DESCENDING

import requests

MACHINE_PREFIX = "mist"

log = getLogger('mist.monitor')

requests_log = getLogger("requests")
requests_log.setLevel(WARNING)

def resize_stats(stats, nr_requested):
    """Returns stats that match the requested size.

    If the requested equal the available simply return them. If they are less
    than the requested pad zeros and if they are more use spline interpolation
    to offer more accurate results.

    The stats argument must be a numpy.array() object and the return value is
    a list so you can serve directly in a JSON.

    .. note:: In spline interpolation this also applies abs() to the returned
              values, so be careful if there are negative values to return.
    """
    nr_available = stats.shape[0]

    if nr_available == nr_requested:
        resized_stats = stats
    elif nr_available < nr_requested:
        # pad zeros
        resized_stats = numpy.zeros(nr_requested)
        if nr_requested != 0:
            resized_stats[-nr_available::] = stats
        for x in range(resized_stats.shape[0] - len(stats) - 1,resized_stats.shape[0]):
            if resized_stats[x] != resized_stats[x]:
               log.warn("Got NaN for a value, zeroing it :S")
               resized_stats[x] = 0
    else:
        # use spline interpolation, if it is possible to solve
        sampling_step = float(nr_available) / nr_requested
        try:
            x_axis = numpy.arange(nr_available)
            spline = interpolate.splrep(x_axis, stats)
            new_x_axis = numpy.arange(0, nr_available, sampling_step)
            resized_stats = interpolate.splev(new_x_axis, spline, der=0)
            resized_stats = numpy.abs(resized_stats)
        except:
            log.warn('Unable to solve spline')
            resized_stats = stats[0::sampling_step]

    if resized_stats.shape:
        return list(resized_stats)
    else:
        # if resized stats is a single number then list() will fail
        return [resized_stats]


def graphite_build_inner_disk_read_target(uuid):
    """
    """

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)

    #disk_types = ['disk_merged', 'disk_octets', 'disk_ops', 'disk_time' ]
    disk_type = 'disk_octets'
    target = 'derivative(sumSeries(%s.disk-*.%s.read))' % (vm_hostname, disk_type)

    return target


def graphite_build_disk_read_target(uuid):
    """
    """

    target = graphite_build_inner_disk_read_target(uuid)

    target_all = 'summarize(transformNull(%s, 0), "STEPsecs", "avg")' % (target)
    target_uri = "target=alias(%s,'disk-read')" % (target_all)

    return target_uri


def graphite_build_inner_disk_write_target(uuid):
    """
    """

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)

    #disk_types = ['disk_merged', 'disk_octets', 'disk_ops', 'disk_time' ]
    disk_type = 'disk_octets'
    target = 'derivative(sumSeries(%s.disk-*.%s.write))' % (vm_hostname, disk_type)

    return target


def graphite_build_disk_write_target(uuid):
    """
    """

    target = graphite_build_inner_disk_write_target(uuid)

    target_all = 'summarize(transformNull(%s, 0), "STEPsecs", "avg")' % (target)
    target_uri = "target=alias(%s,'disk-write')" % (target_all)

    return target_uri


def graphite_build_disk_target(uuid, action=None):
    """
    """

    switch_stat = {'write': graphite_build_disk_write_target,
                   'read': graphite_build_disk_read_target,
                  }


    if not action:
        target_uri = '%s' % (switch_stat['read'](uuid))
        target_uri += '&%s' % (switch_stat['write'](uuid))
    elif action == 'read' or action == 'write':
        target_uri = '%s' % (switch_stat[action](uuid))
    else:
        log.error("No such action %s, returning both" % action)
        target_uri = '%s' % (switch_stat['write'](uuid))
        target_uri += '&%s' % (switch_stat['read'](uuid))

    return target_uri


def graphite_get_disk_stats(uri, uuid, time):
    """
    """

    disk_data = {
             'disks': 1,
             'read': {
                 'xvda1': {
                     'disk_merged': [],
                     'disk_octets': [],
                     'disk_ops': [],
                     'disk_time': []
                 }
             },
             'write': {
                 'xvda1': {
                     'disk_merged': [],
                     'disk_octets': [],
                     'disk_ops': [],
                     'disk_time': []
                 }
             },
        }

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)

    #FIXME: minimize graphite queries -- This is unacceptable!
    #commenting out the other values -- not sure we actually need them
    #disk_types = ['disk_merged', 'disk_octets', 'disk_ops', 'disk_time' ]
    disk_types = ['disk_octets']
    for disk_type in disk_types:

        target = 'derivative(sumSeries(%s.disk-*.%s.read))' % (vm_hostname, disk_type)

        complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time)

        list_data = graphite_issue_request(complete_uri)

        disk_data['read']['xvda1'][disk_type] = list_data

        if not list_data:
            log.warn("DISK data empty :S")
            return disk_data

    for disk_type in disk_types:

        target = 'derivative(sumSeries(%s.disk-*.%s.write))' % (vm_hostname, disk_type)

        complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time)

        list_data = graphite_issue_request(complete_uri)

        disk_data['write']['xvda1'][disk_type] = list_data

        if not list_data:
            log.warn("DISK data empty :S")

    ret = disk_data
    return ret


def graphite_get_massive_stats(host, port, uuid, expression, start, stop, step):
    """Returns stats from graphite.
    """
    switch_stat = {'cpu': graphite_build_inner_cpu_target,
                   'memory': graphite_build_inner_mem_target_v2,
                   'load': graphite_build_inner_load_target,
                   'network': graphite_build_net_target,
                   'disk': graphite_build_disk_target
                  }

    uri = "http://%s:%d" %(host, port)

    INTERVAL = 10
    if step < INTERVAL:
        step = INTERVAL
    #FIXME: we ask for one more number in order to skip the first one returned.
    #In the case of derivatives we get None and D3 chokes on this.
    if stop - start == step:
        start = start - step
    time_interval = "&from=%s&until=%s" % (start - 2*step, stop - step)
    nrstats = (stop - start) / step

    print "Start : %s" % start
    print "Stop: %s" % stop
    print "Step: %s" % step
    print "nrstats: %s" % nrstats

    ret = {}
    retval = {}

    step_str = str(step)
    massive_target = ""
    for target in expression:
        # FIXME: will incororate this for zooming in/out of a specific time
        # period, major TODO
        if target in ['disk', 'network']:
            iter_target = '%s' % (switch_stat[target](uuid).replace('STEP', step_str))
        else:
            iter_target = 'target=alias(summarize(transformNull(%s, 0), "%dsecs", "avg"), "%s")' % (switch_stat[target](uuid), step, target.replace("memory", "mem"))
        #iter_target = '%s' % (switch_stat[target](uuid))
        massive_target += iter_target + "&"
        #print iter_target

    complete_uri = "%s/render?%s%s&format=json" % (uri, massive_target, time_interval)

    ret = graphite_issue_massive_request(complete_uri, nrstats)

    for target in expression:
        if target == 'cpu':
            if ret.has_key('cpu'):
                retval[target] = {'cores': 1, 'utilization': ret['cpu']}
            else:
                retval[target] = {'cores': 1, 'utilization': [0]}
        if target == 'disk':
            if ret.has_key('disk-read'):
                retval[target] = {'disks': 1, 'read': {'xvda1': {'disk_octets': ret['disk-read']}}}
            else:
                retval[target] = {'disks': 1, 'read': {'xvda1': {'disk_octets': [0]}}}
            if ret.has_key('disk-write'):
                retval[target]['write'] = {'xvda1': {'disk_octets': ret['disk-write']}}
            else:
                retval[target]['write'] = {'xvda1': {'disk_octets': [0]}}

        if target == 'network':
            if ret.has_key('net-recv'):
                retval[target] =  {'eth0': {'rx': ret['net-recv']}}
            else:
                retval[target] =  {'eth0': {'rx': [0]}}
            if ret.has_key('net-send'):
                retval[target]['eth0']['tx'] = ret['net-send']
            else:
                retval[target]['eth0']['tx'] = [0]

        if target == 'memory':
            #if ret.has_key('mem-total'):
            #    if len(ret['mem-total']) > 0:
            #        if ret['mem-total'][0] == None:
            #            total = 0
            #        else:
            #            total = ret['mem-total'][0]
            #else:
            #    total = 0
            if ret.has_key('mem'):
                retval[target] = ret['mem']
            else:
                retval[target] = [0]

        if target == 'load':
            if ret.has_key('load'):
                retval[target] = ret['load']
            else:
                retval[target] = [0]

    """
    {'cpu': {'cores': 1, 'utilization': ret['cpu']},
     'disk': {'disks': 1,
      'read': {'xvda1': {'disk_ops': ret['disk-read']} },
      'write': {'xvda1': {'disk_ops': ret['disk-write']} },
         },
     'load': ret['load'],
     'memory': {'total': ret['mem-total'][0], 'used': ret['mem']},
     'network': {'eth0': {'rx': ret['net-recv'], 'tx': ret['net-send']}}}
    """

    """

    {u'cpu': {u'cores': 1, u'utilization': ret['cpu']},
     u'disk': {u'disks': 1,
      u'read': {u'xvda1': {u'disk_merged': [10, 10],
        u'disk_octets': [117811200, 117811200],
        u'disk_ops': [11228, 11228],
        u'disk_time': [345, 345]}},
      u'write': {u'xvda1': {u'disk_merged': [69292, 69291],
        u'disk_octets': [1218277376, 1218248704],
        u'disk_ops': [135415, 135409],
        u'disk_time': [153624, 153620]}}},
     u'load': [0.0],
     u'memory': {u'total': 116170752.0, u'used': [64438272.0]},
     u'network': {u'eth0': {u'rx': [0.04453676453899832],
       u'tx': [0.09384519690292271]}}}
    """

    log.debug("return value (massive stats) %s" % retval)
    return retval


def dummy_get_stats(expression, start, stop, step):
    """Returns simulated stats.

    .. warning:: Needs more realistic values in network and memory
    """
    nr_asked = int((stop - start) / step)

    cpu_cores = numpy.random.randint(1, 2)
    cpu_util = list(numpy.random.rand(nr_asked) * cpu_cores)

    load = list(numpy.random.rand(nr_asked))

    memory_total = numpy.random.randint(12800, 12800* 100)
    memory_used = numpy.random.rand(nr_asked) * memory_total
    memory_used = list(memory_used)

    network_rx = list(numpy.random.rand(nr_asked) * 50)
    network_tx = list(numpy.random.rand(nr_asked) * 50)

    stats = {
        'cpu': {
            'utilization': cpu_util,
            'cores': cpu_cores
        },
        'load': load,
        'memory': {
            'used': memory_used,
            'total': memory_total
        },
       'disk': {
             'disks': 1,
             'read': {
                 'xvda1': {
                     'disk_merged': [10, 10],
                     'disk_octets': [117811200, 117811200],
                     'disk_ops': [11228, 11228],
                     'disk_time': [345, 345]
                 }
             },
             'write': {
                 'xvda1': {
                     'disk_merged': [69292, 69291],
                     'disk_octets': [1218277376, 1218248704],
                     'disk_ops': [135415, 135409],
                     'disk_time': [153624, 153620]
                 }
             },
        },
        'network': {
            'eth0': {
                'rx': network_rx,
                'tx': network_tx
            }
        }
    }

    return stats
