"""Module for getting stats from different monitoring backends.

It currently supports mongodb and there is some previous work on graphite and
dummy, which don't work right now.

From collectd we need stats for cpu, load, memory, network and disks.

Collectd returns these values in the following format:

We return only a subset of these values to save json size. The format we
return is the following:
"""
#import requests            # used in grapite
from datetime import datetime
from time import time

#import math                # used in dummy
#from random import gauss   # used in dummy
import numpy
from scipy import interpolate as scinterp

from logging import getLogger

from pymongo import Connection
from pymongo import DESCENDING
from mist.monitor.config import MONGODB
import pymongo


log = getLogger('mist.monitor')


def pad_zeros(stats, old_size, new_size):
    """Pads zeros to create a new array from stats with size == new_size."""
    for stat in stats:
        padded = numpy.zeros(new_size)
        padded[-old_size::] = stats[stat]
        stats[stat] = padded

    return stats


def interpolate(stats, old_size, sampling_step):
    """Returns interpolated stats, using spline interpolation

    .. note:: This also applies abs() to the returned values
    """
    x_axis = numpy.arange(old_size)
    new_x_axis = numpy.arange(0, old_size, sampling_step)

    for stat in stats:
        fitted = scinterp.splrep(x_axis, stats[stat])
        stats[stat] = scinterp.splev(new_x_axis, fitted, der=0)
        # FIXME: is this useful for every case?
        stats[stat] = numpy.abs(stats[stat])

    return stats


def mongo_get_cpu_stats(db, uuid, start, stop, step):
    res = {}
    nr_values_asked = int((stop - start)/step)
    ret = {'total': [],'util': [],'total_diff':[] ,'used_diff': [] ,
                'used' : [] }

    query_dict = {'host': uuid,
                  'time': {"$gte": datetime.fromtimestamp(int(start)),
                           "$lt": datetime.fromtimestamp(int(stop)) }}

    res = db.cpu.find(query_dict).sort('time', DESCENDING)

    prev = None
    set_of_cpus = []
    for r in res:
        curr = r['time']
        index = r['type_instance']
        value = r['values']
        cpu_no = r['plugin_instance']
        if not ret.get(index, None):
            ret[index] = value
        else:
            ret[index].extend(value)

        if cpu_no not in set_of_cpus:
            set_of_cpus.append(cpu_no)

        if prev != curr:
            ret['total'].append(0)
            ret['used'].append(0)

        if index != 'idle':
            ret['used'][-1] += float(value[0])
        ret['total'][-1] += value[0]
        prev = curr

    for j in range(1, len(ret['total'])):
        i = len(ret['total']) -1 - j
        ret['total_diff'].append  (abs(ret['total'][i-1] - ret['total'][i]))
        ret['used_diff'].append(abs(ret['used'][i-1] - ret['used'][i]))

    used_diff = numpy.array(ret['used_diff'])
    total_diff = numpy.array(ret['total_diff'])
    util = used_diff / total_diff
    calc_util = util

    if util.shape[0] < nr_values_asked:
        calc_util = numpy.zeros(nr_values_asked)
        calc_util[-util.shape[0]::] = util
    elif util.shape[0] > nr_values_asked:
        x_axis = numpy.arange(util.shape[0])
        tck = scinterp.splrep(x_axis, util)
        new_x_axis = numpy.arange(0, util.shape[0], util.shape[0] * float(step)/(stop-start))
        calc_util = scinterp.splev(new_x_axis, tck, der=0)
        calc_util = numpy.abs(calc_util)

    ret['util'] = list(calc_util)

    return ret


def mongo_get_load_stats(db, uuid, start, stop, step):
    """Returns machine's load stats from mongo.

    .. note:: Although it collects all, it returns only the short term load,
              for smaller response size.
    """
    query_dict = {
        'host': uuid,
        'time': {
            '$gte': datetime.fromtimestamp(int(start)),
            '$lt': datetime.fromtimestamp(int(stop))
        }
    }
    docs = db.load.find(query_dict).sort('time', DESCENDING)

    stats = {
        'shortterm': [],
        'midterm': [],
        'longterm':[]
    }

    for doc in docs:
        stats['shortterm'].append(doc['values'][0])
        stats['midterm'].append(doc['values'][1])
        stats['longterm'].append(doc['values'][2])

    nr_asked = int((stop - start)/step)
    nr_returned =len(stats['shortterm'])

    if nr_asked == nr_returned:
        # All values
        # ----------
        # return stats

        # Most important values
        # ---------------------
        return stats['shortterm']
    else:
        calc_stats = {
            'shortterm': numpy.array(stats['shortterm']),
            'midterm': numpy.array(stats['midterm']),
            'longterm': numpy.array(stats['longterm'])
        }
        if nr_returned < nr_asked:
            calc_stats = pad_zeros(calc_stats, nr_returned, nr_asked)
        else:
            # When nr_returned > nr_asked:
            sampling_step = nr_returned * float(step) / (stop - start)
            calc_stats = interpolate(calc_stats, nr_returned, sampling_step)

        # All values
        # ----------
        # stats = {
        #     'shortterm': list(calc_stats['shortterm']),
        #     'midterm': list(calc_stats['midterm']),
        #     'longterm': list(calc_stats['longterm'])
        # }

        # Most important values
        # ---------------------
        return list(calc_stats['shortterm'])


def mongo_get_memory_stats(db, uuid, start, stop, step):
    """Returns machine's memory stats from mongo.

    .. note:: Although it collects all, it returns only a list of memory used
              and a single number for total memory, for smaller response size.
    """
    query_dict = {
        'host': uuid,
        'time': {
            '$gte': datetime.fromtimestamp(int(start)),
            '$lt': datetime.fromtimestamp(int(stop))
        }
    }
    docs = db.memory.find(query_dict).sort('time', DESCENDING)

    stats = {
        'free': [],
        'used': [],
        'cached':[],
        'buffered': [],
        'total': 0
    }

    for doc in docs:
        stats[doc['type_instance']].append(doc['values'][0])

    nr_asked = int((stop - start)/step)
    nr_returned =len(stats['free'])

    stats['total'] = stats['free'][0] + stats['used'][0]

    if nr_asked == nr_returned:
        # All values
        # ----------
        # return stats

        # Most important values
        # ---------------------
        return {'used': stats['used'], 'total': stats['total']}
    else:
        calc_stats = {
            'free': numpy.array(stats['free']),
            'used': numpy.array(stats['used']),
            'cached': numpy.array(stats['cached']),
            'buffered': numpy.array(stats['buffered'])
        }
        if nr_returned < nr_asked:
            calc_stats = pad_zeros(calc_stats, nr_returned, nr_asked)
        else:
            # When nr_returned > nr_asked:
            sampling_step = nr_returned * float(step) / (stop - start)
            calc_stats = interpolate(calc_stats, nr_returned, sampling_step)

        # All values
        # ----------
        # stats = {
        #     'free': list(calc_stats['free']),
        #     'used': list(calc_stats['used']),
        #     'cached': list(calc_stats['cached'])
        #     'buffered': list(calc_stats['buffered'])
        #     'total': stats['total'])
        # }

        # Most important values
        # ---------------------
        return {'used': list(calc_stats['used']), 'total': stats['total']}


def calculate_network_speed(previous, current):

    bytes_diff = (current['value'] - previous['value'])
    timestamp_diff = (current['timestamp'] - previous['timestamp'])

    return float(bytes_diff) / timestamp_diff


def mongo_get_network_stats(db, uuid, start, stop, step):

    res = {}
    nr_values_asked = int((stop - start)/step)

    query_dict = {'host': uuid,
                  'time': {"$gte": datetime.fromtimestamp(int(start)),
                           "$lt": datetime.fromtimestamp(int(stop)) }}

    #XXX: No need to use limit, we just return all values in the requested time range
    res = db.interface.find(query_dict).sort('time', pymongo.DESCENDING)
    #.limit(2*8*(int((stop-start)/step)))

    ret = { }
    set_of_ifaces = db.interface.distinct('type_instance') #db.interface.distinct('type_instance', {'host':uuid})
    set_of_fields = db.interface.distinct('dsnames')
    set_of_data = db.interface.distinct('type')
    if "" in set_of_ifaces:
        set_of_ifaces.remove("")

    for iface in set_of_ifaces:
        ret[iface] = {}
        ret[iface]['total'] = []
        ret['timestamp'] = []
        ret[iface]['speed'] = {'rx': [], 'tx': [] }

        for index in set_of_data:
            ret[iface][index] = {}
            for field in set_of_fields:
               ret[iface][index][field] = []
    current = { 'value': [], 'timestamp': 0}
    previous = { 'value': [], 'timestamp': 0}

    prev = None
    for r in res:
        curr = r['time']
        iface = r['type_instance']
        value = r['values']
        index = r['type']

        if prev != curr:
            ret[iface]['total'].append(0)
            ret['timestamp'].append(curr.strftime("%s"))

        if not ret.get(index, None):
            for field in set_of_fields:
                #get values for ['rx'] and ['tx'], use .index(field) to get
                #the idx of the relevant field
                list_ptr = ret[iface][index][field]
                idx = set_of_fields.index(field)
                list_ptr.append(value[idx])
                nr_stored = len(list_ptr)
                #ugly check to make sure we have 2 or more values to calculate
                #the diff
                if nr_stored > 1 and index == 'if_octets':
                    current['value'] = list_ptr[-1]
                    previous['value'] = list_ptr[-2]
                    current['timestamp'] = int(ret['timestamp'][-1])
                    previous['timestamp'] = int(ret['timestamp'][-2])
                    speed = calculate_network_speed(current, previous)
                    ret[iface]['speed'][field].append(speed)
        prev = curr

    return ret


def mongo_get_stats(uuid, expression, start, stop, step):
    """Returns stats for the machine with the given uuid from the mongodb
    backend.
    """
    connection = Connection(MONGODB['host'], MONGODB['port'])
    db = connection[MONGODB['dbname']]

    stats = {}
    for exp in expression:
        #print exp
        if exp == 'cpu':
            stats[exp] = mongo_get_cpu_stats(db, uuid, start, stop, step)
        if exp == 'load':
            stats[exp] = mongo_get_load_stats(db, uuid, start, stop, step)
        if exp == 'memory':
            stats[exp] = mongo_get_memory_stats(db, uuid, start, stop, step)
        if exp == 'network':
            stats[exp] = mongo_get_network_stats(db, uuid, start, stop, step)

    return stats


def graphite_get_stats(uuid, expression, start, stop, step):
    """Returns stats from graphite.

    .. warning:: I doesn't work, needs rewrite to fit the client API
    """

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
    """
    return {}


def dummy_get_stats(expression, start, stop, step):
    """Returns simulated stats.

    .. warning:: I doesn't work, needs rewrite to fit the client API
    """
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

    log.info(ret)
    return ret
    """
    return {}
