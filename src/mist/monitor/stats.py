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

import numpy
from scipy import interpolate

from logging import getLogger

from pymongo import Connection
from pymongo import DESCENDING
from mist.monitor.config import MONGODB


log = getLogger('mist.monitor')


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

def mongo_get_cpu_stats(db, uuid, start, stop, step):
    """Returns machine's cpu stats from mongo.

    Initially stats get populated from the query results like this::

        stats = {
            '0': {
                'user': [...],
                'nice': [...],
                'system': [...],
                'idle': [...],
                'wait': [...],
                'interrupt': [...],
                'softirq': [...],
                'steal': [...]
            },

            ....,

            'N': {
                ....
            }
        }

    where 0, ..., N are the available cores.

    Then cpu utilization is calculated with::

        ((total_t - total_(t-1)) - (idle_t - idle_(t-1)) / (total_t - total_t-1)

    .. note:: Although it collects all, it returns only a list of total cpu
              utilization across all cores and the number of available cores,
              for smaller response size.
    """

    #when asked one value, we have to get one more to
    #calculate the CPU utilization
    interval = 5
    query_dict_total = {
        "host": uuid,
        "time": {
            "$gte": datetime.fromtimestamp(int(start - interval)),
            "$lt": datetime.fromtimestamp(int(stop))
        }
    }

    group_dict = {
        "$group": {
            "_id": {
                "plugin_instance": "$plugin_instance",
                "time": "$time"
            },
            "user_values": {
                '$push': "$values"
            },
            "stat_type": {
                '$push': "$type_instance"
            }
        }
    }

    #get number of different stat types
    stat_types = db.cpu.find(query_dict_total).distinct("type_instance")

    #build the form of the aggregate query
    pipeline = [{"$match": query_dict_total}, group_dict]
    #do the actual query
    res = db.command('aggregate', 'cpu', pipeline=pipeline)

    #pretify
    res_ptr = res['result']
    if len(res_ptr) < 2:
        log.warn("Cannot calculate CPU utilization with less than 2 values")
        return {'utilization': [], 'cores': None }

    stats = {}
    for x in res_ptr:
        stat_type = x['stat_type']
        #timestamp = x['_id']['time']
        core = x['_id']['plugin_instance']
        val_list = x['user_values']
        if len(val_list) != len(stat_types):
           #FIXME: if we don't want to ignore these values, we have to
           #find a way to produce dummy values for the missing items
           log.warn("Will ignore this item -- invalid: %s" %x)
           continue
        if not stats.get(core, None):
            stats[core] = {}
        for stat in stat_type:
            if not stats[core].get(stat, None):
                stats[core][stat] = []

            ptr = stats[core][stat]
            ptr.extend(val_list[stat_type.index(stat)])

    nr_cores = 0
    utilization = {}
    for core in stats:
        # counting how many cores are there
        nr_cores += 1
        # Arrange stats in a 2D array where each line is a stat type and each
        # column a timestamp. Every row should have the same length. The first
        # row will be full of zeros, just to enable vstacking.
        arr_stats = numpy.zeros(len(stats[core]['user']))
        for stat_type in stats[core]:
            row = numpy.array(stats[core][stat_type])
            arr_stats = numpy.vstack((arr_stats, row))
        # sum along every column
        totals = arr_stats.sum(0)
        idles = numpy.array(stats[core]['idle'])
        # roll to create total_t-1, eg total = [a,b,c] -> prev = [b,c,a]
        totals_prev = numpy.roll(totals, -1)
        idles_prev = numpy.roll(idles, -1)
        utilization[core] = ((totals - totals_prev) - (idles - idles_prev)) /\
                            (totals - totals_prev)
        utilization[core] = numpy.abs(utilization[core])

    # Prepare return, sum utilization across all cores
    nr_asked = int((stop - start) / step)
    sum_utilization = numpy.zeros(nr_asked)
    for core in stats:
        #instead of adding up all utilizations per core and resizing afterwards,
        #we resize each core's separate utilization and sum them up to account
        #for missing values (see comments above -- ignore items)
        sum_utilization += resize_stats(utilization[core], nr_asked)

    return {'utilization':list(sum_utilization), 'cores': nr_cores}


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

    # Prepare return, only shortterm for now
    nr_asked = int((stop - start) / step)
    shortterm = resize_stats(numpy.array(stats['shortterm']), nr_asked)

    return shortterm


def mongo_get_disk_stats(db, uuid, start, stop, step):
    """Returns machine's disk stats from mongo.

    """

    query_dict = {
        "host": uuid,
        "time": {
            "$gte": datetime.fromtimestamp(int(start)),
            "$lt": datetime.fromtimestamp(int(stop))
        }
    }

    group_dict = {
        "$group": {
            "_id": {
                "plugin_instance": "$plugin_instance",
                "time": "$time"
            },
            "user_values": {
                '$push': "$values"
            },
            "stat_type": {
                '$push': "$type"
            }
        }
    }

    #we explicitely need to sort the result. Maybe we need to do that
    #in the cpu case too
    sort_dict = {
        "$sort": {
            "time": -1,
            "_id": -1
        }
    }

    #get number of different stat types
    stat_types = db.disk.find(query_dict).distinct("type")

    #build the form of the aggregate query
    pipeline = [{"$match": query_dict}, group_dict, sort_dict]

    #do the actual query
    res = db.command('aggregate', 'disk', pipeline=pipeline)

    #pretify
    res_ptr = res['result']
    if len(res_ptr) < 2:
        log.warn("Cannot return just one value :S")
        return {'read': [], 'write': [], 'disks': None }

    stats = { 'read': {}, 'write': {}}
    for row in res_ptr:
        stat_type = row['stat_type']
        #timestamp = row['_id']['time']
        disk = row['_id']['plugin_instance']
        val_list = row['user_values']
        if len(val_list) != len(stat_types):
           #FIXME: if we don't want to ignore these values, we have to
           #find a way to produce dummy values for the missing items
           log.warn("Will ignore this item -- invalid: %s" %row)
           continue
        if not stats['read'].get(disk, None):
            stats['read'][disk] = {}
        if not stats['write'].get(disk, None):
            stats['write'][disk] = {}
        for stat in stat_type:
            if not stats['read'][disk].get(stat, None):
                stats['read'][disk][stat] = []
            if not stats['write'][disk].get(stat, None):
                stats['write'][disk][stat] = []

            ptr_read = stats['read'][disk][stat]
            ptr_read.append(val_list[stat_type.index(stat)][0])

            ptr_write = stats['write'][disk][stat]
            ptr_write.append(val_list[stat_type.index(stat)][1])

    # Prepare return, only used and total for now
    nr_asked = int((stop - start) / step)
    read = stats['read']
    write = stats['write']

    return {'read': read, 'write': write, 'disks': len(stats['read'])}


def mongo_get_df_stats(db, uuid, start, stop, step):
    """Returns machine's df stats from mongo.

    .. note:: Although it collects all, it returns only a list of FS used
              and a single number for total FS, for smaller response size.
    """
    query_dict = {
        'host': uuid,
        'time': {
            '$gte': datetime.fromtimestamp(int(start)),
            '$lt': datetime.fromtimestamp(int(stop))
        }
    }
    docs = db.df.find(query_dict).sort('time', DESCENDING)

    stats = {}

    for doc in docs:
        fs = doc['type_instance']
        used_val = float(doc['values'][0])
        free_val = float(doc['values'][1])
        if not stats.get(fs, None):
            stats[fs] = {
                'used': [used_val],
                'free': [free_val],
                'total': [free_val + used_val]
            }
        else:
            stats[fs]['used'].append(used_val)
            stats[fs]['free'].append(free_val)
            stats[fs]['total'].append(used_val + free_val)

    # Prepare return, only used and total for now
    nr_asked = int((stop - start) / step) + 1

    used = {}
    total = {}
    for fs in stats:
        used[fs] = resize_stats(numpy.array(stats[fs]['used']), nr_asked)
        total[fs] = resize_stats(numpy.array(stats[fs]['total']), nr_asked)

    return {'used': used, 'total': total}


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
    }

    for doc in docs:
        stats[doc['type_instance']].append(doc['values'][0])

    # Prepare return, only used and total for now
    total_memory = stats['free'][0] + stats['used'][0]

    nr_asked = int((stop - start) / step)
    used = resize_stats(numpy.array(stats['used']), nr_asked)

    return {'used': used, 'total': total_memory}


def mongo_get_network_stats(db, uuid, start, stop, step):
    """Returns machine's network stats from mongo.

    Initially stats get populated from the query results like this::

        stats = {
            'lo': {
                if_octets: {
                    'rx': [...],
                    'tx': [...]
                },
                if_packets: {
                    'rx': [...],
                    'tx': [...]
                }
                if_errors: {
                    'rx': [...],
                    'tx': [...]
                }
            },

            'eth0': {
                if_octets: {
                    'rx': [...],
                    'tx': [...]
                },
                if_packets: {
                    'rx': [...],
                    'tx': [...]
                }
                if_errors: {
                    'rx': [...],
                    'tx': [...]
                }
            },

            ....,

            'ethN': {
                ....
            }
        }

    The basic keys are the available network interfaces. To calcutate speed
    the if_octets values are used and timestamps are saved in a different
    list.

    .. note:: Although it collects all, it returns only the eth0 speed, which
              is usually public, for smaller response size.
    """
    query_dict = {
        'host': uuid,
        'time': {
            '$gte': datetime.fromtimestamp(int(start)),
            '$lt': datetime.fromtimestamp(int(stop))
        }
    }
    docs = db.interface.find(query_dict).sort('time', DESCENDING)

    stats = {}
    speed = {}
    timestamps = []
    for doc in docs:
        iface = doc['type_instance']
        stat_type = doc['type']
        if not stats.get(iface, None):
            stats[iface] = {}
            speed[iface] = {}
        if not stats[iface].get(stat_type, None):
            stats[iface][stat_type] = {
                'rx': [float(doc['values'][0])],
                'tx': [float(doc['values'][1])]
            }
            speed[iface][stat_type] = {'rx': 0, 'tx': 0}
            timestamps.append(int(doc['time'].strftime("%s")))
        else:
            stats[iface][stat_type]['rx'].append(float(doc['values'][0]))
            stats[iface][stat_type]['tx'].append(float(doc['values'][1]))
            timestamps.append(int(doc['time'].strftime("%s")))

    # this list will contain the same timestamp multiple times, so get the
    # unique values only and mirror it to keep the order as it was
    timestamps = numpy.unique(timestamps)
    timpestamps = timestamps[::-1]
    timestamps_prev = numpy.roll(timestamps, 1)
    timestamps_prev[0] = 0
    for iface in stats:
        for stat_type in stats[iface]:
            rx = numpy.array(stats[iface][stat_type]['rx'])
            rx_prev = numpy.roll(rx, 1)
            rx_prev[0] = 0.0
            speed[iface][stat_type]['rx'] = (rx - rx_prev) /\
                                            (timestamps - timestamps_prev)

            tx = numpy.array(stats[iface][stat_type]['tx'])
            tx_prev = numpy.roll(tx, 1)
            tx_prev[0] = 0.0
            speed[iface][stat_type]['tx'] = (tx - tx_prev) /\
                                            (timestamps - timestamps_prev)

    # Prepare return, only if_octets for now
    nr_asked = int((stop - start) / step)

    rx_speed = resize_stats(speed['eth0']['if_octets']['rx'], nr_asked)
    tx_speed = resize_stats(speed['eth0']['if_octets']['tx'], nr_asked)

    return {'eth0': {'rx': rx_speed, 'tx': tx_speed}}


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
        if exp == 'df':
            stats[exp] = mongo_get_df_stats(db, uuid, start, stop, step)
        if exp == 'disk':
            stats[exp] = mongo_get_disk_stats(db, uuid, start, stop, step)

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

    .. warning:: Needs more realistic values in network and memory
    """
    nr_asked = int((stop - start) / step)

    cpu_cores = numpy.random.randint(0, 10)
    cpu_util = list(numpy.random.rand(nr_asked) * cpu_cores)

    load = list(numpy.random.rand(nr_asked))

    memory_total = numpy.random.randint(128000000, 128000000 * 10)
    memory_used = numpy.random.rand(nr_asked) * memory_total
    memory_used = list(memory_used)

    network_rx = list(numpy.random.rand(nr_asked) * 1000)
    network_tx = list(numpy.random.rand(nr_asked) * 1000)

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
        'network': {
            'eth0': {
                'rx': network_rx,
                'tx': network_tx
            }
        }
    }

    return stats
