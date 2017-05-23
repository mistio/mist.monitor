#!/bin/sh

# IF collectd.passwd does not exist, create it
if [ ! -f /opt/mist/collectd.passwd ]; then
    touch /opt/mist/collectd.passwd
fi

python /mist.monitor/src/bucky/bucky.py /bucky_conf.py
