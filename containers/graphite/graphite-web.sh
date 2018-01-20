#!/bin/sh

# sh /opt/graphite/bin/build-index.sh


uwsgi --plugin /usr/lib/uwsgi/python_plugin.so \
    --uid root \
    --master \
    --master-as-root \
    --processes 4 \
    --die-on-term \
    --http-socket 0.0.0.0:8000 \
    --wsgi-file /opt/graphite/webapp/graphite/wsgi.py \
    --chdir /opt/graphite/webapp \
    --harakiri 120 \
    --max-requests 50
