#!/bin/sh

# IF collectd.passwd does not exist, create it
if [ ! -f /opt/mist/collectd.passwd ]; then
    touch /opt/mist/collectd.passwd
fi

cd /
pip install -e /mist.monitor/src/bucky && \
pip install -e /mist.monitor

supervisord -c /etc/supervisord.conf
