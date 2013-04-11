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

from pyramid.response import Response

#import numpy
#from scipy import interpolate

from logging import getLogger

from pymongo import Connection
from pymongo import DESCENDING

import requests

MACHINE_PREFIX = "mist"

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
        iface = doc['plugin_instance']
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

    if not timestamps:
        return {'eth0': {'rx': [], 'tx': []}}

    # this list will contain the same timestamp multiple times, so get the
    # unique values only and mirror it to keep the order as it was
    timestamps = numpy.unique(timestamps)
    timestamps = timestamps[::-1]
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


def mongo_get_stats(backend, uuid, expression, start, stop, step):
    """Returns stats for the machine with the given uuid from the mongodb
    backend.
    """
    connection = Connection(backend['host'], backend['port'])
    db = connection[backend['dbname']]

    stats = {}
    for exp in expression:
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


def graphite_issue_request(uri):
    """ gets data from graphite
    """

    ret = []
    if not uri:
        log.warn("You have to specify the backend's URI")
        return ret

    try:
        req = requests.get(uri, params=None)
    except:
        log.warn("Could not get data from graphite")
        return ret
    
    if req.status_code != 200:
        log.warn("Got response different than 200")
        return ret

    json_len = len(req.json())
    if not json_len:
        log.debug("json length is %d, request_uri = %s" % (json_len, uri))
        return ret
    data = req.json()[0]['datapoints']
    data_len = len(data)
    real_list_data = []
    #print "no of data returned from graphite: %d" %(data_len)
    for x in range(0, data_len):
        #FIXME: is this correct? if graphite returned None, it means that there is
        # no value for this specific timestamp. If we set it to 0 the user could
        # misinterpret this value ...
        if data[x][0] == None:
            data[x][0] = 0
        real_list_data.append(data[x][0])

    ret = real_list_data
    if not ret.__class__ is list:
        log.error("data is not returned correctly. Need a list, got %s" % ret)
        ret = []

    return ret


def graphite_build_cpu_target(uuid):
    """ gets CPU data for a given uuid
    """

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)
    
    #Calculate the sum of all time measurements, excluding the "idle" one
    total_wo_idle_sum = 'sumSeries(exclude(%s.cpu-0.*,"idle"))' % (vm_hostname)

    total_sum = 'sumSeries(%s.cpu-0.*)' % (vm_hostname)
    
    #Calculate the derivative of each sum
    first_set = 'derivative(%s)' % (total_wo_idle_sum)
    second_set = 'derivative(%s)' % (total_sum)
    
    #Divide the first with the second sum (wo_idle_sum / total_sum)
    target = "divideSeries(%s,%s)" % (first_set, second_set)
    
    target_uri = "target=alias(%s,'cpu')" % (target) 

    return target_uri 


def graphite_build_net_target(uuid):
    """
    """

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)
    
    target = 'derivative(%s.interface*.if_octets*.tx)' % (vm_hostname)
    
    target_uri = "target=alias(%s,'net-send')" % (target) 

    target = 'derivative(%s.interface*.if_octets*.rx)' % (vm_hostname)

    target_uri += "&target=alias(%s, 'net-recv')" % (target) 

    return target_uri


def graphite_build_load_target(uuid):
    """
    """

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)
    
    target = '%s.load.load.shortterm' % (vm_hostname)
    
    target_uri = "target=alias(%s,'load')" % (target) 

    return target_uri


def graphite_build_mem_target(uuid):
    """
    """

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)

    target = 'scale(sumSeries(%s.memory.memory-*),0.00097656250000000000)' % (vm_hostname)
    
    target_uri = "target=alias(%s,'mem-total')" % (target) 

    target = 'scale(sumSeries(%s.memory.memory-{buffered,cached,used}),0.00097656250000000000)' % (vm_hostname)
    
    target_uri += "&target=alias(%s,'mem')" % (target) 

    return target_uri


def graphite_build_disk_target(uuid):
    """
    """

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)

    #disk_types = ['disk_merged', 'disk_octets', 'disk_ops', 'disk_time' ]
    disk_type = 'disk_ops'
    target = 'derivative(sumSeries(%s.disk-*.%s.read))' % (vm_hostname, disk_type)
        
    target_uri = "target=alias(%s,'disk-read')" % (target) 
    
    target = 'derivative(sumSeries(%s.disk-*.%s.write))' % (vm_hostname, disk_type)

    target_uri += "&target=alias(%s,'disk-write')" % (target) 
        
    return target_uri


def graphite_get_cpu_stats(uri, uuid, time):
    """ gets CPU data for a given uuid
    """

    #FIXME: curently aggregates utilization for all CPUs -- thus we pass 1 to D3
    cpu_data = { 'utilization': [], 'cores': 1 }

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)
    
    #Calculate the sum of all time measurements, excluding the "idle" one
    total_wo_idle_sum = 'sumSeries(exclude(%s.cpu-0.*,"idle"))' % (vm_hostname)

    total_sum = 'sumSeries(%s.cpu-0.*)' % (vm_hostname)
    
    #Calculate the derivative of each sum
    first_set = 'derivative(%s)' % (total_wo_idle_sum)
    second_set = 'derivative(%s)' % (total_sum)
    
    #Divide the first with the second sum (wo_idle_sum / total_sum)
    target = "divideSeries(%s,%s)" % (first_set, second_set)
    
    complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time) 

    list_data = graphite_issue_request(complete_uri)

    cpu_data['utilization'] = list_data

    if not list_data:
        log.warn("cpu utilization data empty :S")

    ret = cpu_data

    return ret


def graphite_get_net_stats(uri, uuid, time):
    """
    """

    #FIXME: curently works for a single interface
    net_data = { 'eth0': { 'rx': [], 'tx': []} }

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)
    
    #FIXME: we may want to return KB instead of just bytes -- if we do, we have to 
    #scale to 1/1024
    #FIXME: find a way to handle rx and tx at the same time. Maybe we could get graphite 
    #to return a dict with 2 lists, 'tx' and 'rx'.
    #target = 'scale(derivative(%s.interface-eth0.if_octets.tx), 0.00012207031250000000)'
    target = 'derivative(%s.interface-eth0.if_octets.tx)' % (vm_hostname)
    
    complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time) 

    list_data = graphite_issue_request(complete_uri)

    net_data['eth0']['tx'] = list_data

    if not list_data:
        log.warn("NET TX data empty :S")

    target = 'derivative(%s.interface-eth0.if_octets.rx)' % (vm_hostname)
    
    complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time) 

    list_data = graphite_issue_request(complete_uri)

    net_data['eth0']['rx'] = list_data

    if not list_data:
        log.warn("NET RX data empty :S")

    ret = net_data
    return ret


def graphite_get_load_stats(uri, uuid, time):
    """
    """

    load_data = []

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)
    
    target = '%s.load.load.shortterm' % (vm_hostname)
    
    complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time) 

    list_data = graphite_issue_request(complete_uri)

    load_data = list_data

    if not list_data:
        log.warn("LOAD data empty :S")

    ret = load_data
    return ret


def graphite_get_mem_stats(uri, uuid, time):
    """
    """

    mem_data = {'total': 0, 'used': [] }

    vm_hostname = "%s-%s" %(MACHINE_PREFIX, uuid)

    #FIXME: find a way to calculate the total memory without querying graphite!
    
    target = 'scale(sumSeries(%s.memory.memory-*),0.00097656250000000000)' % (vm_hostname)
    
    complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time) 

    list_data = graphite_issue_request(complete_uri)

    if not list_data:
        log.warn("MEM data empty :S")
        return mem_data

    mem_data['total'] = list_data[0]

    target = 'scale(sumSeries(%s.memory.memory-{buffered,cached,used}),0.00097656250000000000)' % (vm_hostname)
    
    complete_uri = "%s/render?target=%s%s&format=json" % (uri, target, time) 

    list_data = graphite_issue_request(complete_uri)

    mem_data['used'] = list_data

    if not list_data:
        log.warn("MEM data empty :S")

    ret = mem_data
    return ret


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
    disk_types = ['disk_ops']
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


def graphite_issue_massive_request(uri, nrstats):
    """ gets data from graphite
    """

    ret = []
    if not uri:
        log.warn("You have to specify the backend's URI")
        return ret

    try:
        req = requests.get(uri, params=None)
    except:
        log.warn("Could not get data from graphite")
        return ret
    
    if req.status_code != 200:
        log.warn("Got response different than 200")
        return ret

    json_len = len(req.json())
    if not json_len:
        log.debug("json length is %d, request_uri = %s" % (json_len, uri))
        return ret
    real_list_data = {}

    for i in range(0, json_len):
        data = req.json()[i]['datapoints']
        data_len = len(data)
        index = req.json()[i]['target']
        real_list_data[index] = []
        log.warn("%s %d %d" % (index, data_len, nrstats))
        real_list_data[index] = [j[0] for j in data]
        #real_list_data[index] = [j[0] if j[0].__class__ in [float,int] else 0.1 for j in data]
        if (len(real_list_data[index]) > 1):
            real_list_data[index] = real_list_data[index][1:]
        else:
            log.warn("not enough data to skip the first one :S")

    #log.warn(real_list_data)
    ret = real_list_data
    #print real_list_data
#    if not ret.__class__ is list:
#        log.error("data is not returned correctly. Need a list, got %s" % ret)
#        ret = []

    return ret

def graphite_get_massive_stats(host, port, uuid, expression, start, stop, step):
    """Returns stats from graphite.
    """
    switch_stat = {'cpu': graphite_build_cpu_target,
                   'memory': graphite_build_mem_target,
                   'load': graphite_build_load_target,
                   'network': graphite_build_net_target,
                   'disk': graphite_build_disk_target 
                  }

    uri = "http://%s:%d" %(host, port)

    #FIXME: we ask for one more number in order to skip the first one returned.
    #In the case of derivatives we get None and D3 chokes on this. 
    time = "&from=%s&until=%s" % (start - step, stop)
    nrstats = (stop - start) / step

    ret = {}
    retval = {}

    massive_target = ""
    for target in expression:
        massive_target += switch_stat[target](uuid) + "&"

    complete_uri = "%s/render?%s%s&format=json" % (uri, massive_target, time) 

    ret = graphite_issue_massive_request(complete_uri, nrstats)
    
    for target in expression:
        if target == 'cpu': 
            if ret.has_key('cpu'):
                retval[target] = {'cores': 1, 'utilization': ret['cpu']}
            else:
                retval[target] = {'cores': 1, 'utilization': [0]}
        if target == 'disk': 
            if ret.has_key('disk-read'):
                retval[target] = {'disks': 1, 'read': {'xvda1': {'disk_ops': ret['disk-read']}}}
            else:
                retval[target] = {'disks': 1, 'read': {'xvda1': {'disk_ops': [0]}}}
            if ret.has_key('disk-write'):
                retval[target]['write'] = {'xvda1': {'disk_ops': ret['disk-write']}}
            else:
                retval[target]['write'] = {'xvda1': {'disk_ops': [0]}}

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
            if ret.has_key('mem-total'):
                if len(ret['mem-total']) > 0:
                    if ret['mem-total'][0] == None:
                        total = 0
                    else:
                        total = ret['mem-total'][0]
            else:
                total = 0
            if ret.has_key('mem'):
                retval[target] = {'total': total, 'used': ret['mem']}
            else:
                retval[target] = {'total': total, 'used': [0]}

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

    return retval

def graphite_get_stats(host, port, uuid, expression, start, stop, step):
    """Returns stats from graphite.
    """

    uri = "http://%s:%d" %(host, port)

    time = "&from=%s&until=%s" % (start, stop)
    ret = {}

    ret = graphite_get_massive_stats(host, port, uuid, expression, start, stop, step)
    
    #cpu_data = graphite_get_cpu_stats(uri, uuid, time)
    #
    #net_data = graphite_get_net_stats(uri, uuid, time)
    #
    #load_data = graphite_get_load_stats(uri, uuid, time)
    #
    #mem_data = graphite_get_mem_stats(uri, uuid, time)
    #
    #disk_data = graphite_get_disk_stats(uri, uuid, time)
    #
    #ret['cpu'] = cpu_data
    #ret['network'] = net_data
    #ret['load'] = load_data
    #ret['memory'] = mem_data
    #ret['disk'] = disk_data

    return ret


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
