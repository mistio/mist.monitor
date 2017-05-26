#!/bin/sh

# IF collectd.passwd does not exist, create it
if [ ! -f /opt/mist/collectd.passwd ]; then
    touch /opt/mist/collectd.passwd
fi

uwsgi --plugin /usr/lib/uwsgi/python_plugin.so --http-socket 0.0.0.0:80 --paste-logger --ini-paste /uwsgi.ini
