FROM mist/alpine:3.4
MAINTAINER mist.io <support@mist.io>

RUN apk add --update --no-cache gcc py-crypto flex automake bison \
    pkgconfig cryptsetup-libs rrdtool perl-dev \
    inotify-tools supervisor

COPY requirements.txt /mist.monitor/requirements.txt

WORKDIR /mist.monitor

RUN pip install --no-cache-dir -r /mist.monitor/requirements.txt

COPY . /mist.monitor

RUN pip install -e /mist.monitor/src/bucky && \
    pip install -e /mist.monitor && \
    mkdir -p /opt/mist

COPY containers/monitor/bucky_conf.py /bucky_conf.py

COPY containers/monitor/uwsgi.ini /uwsgi.ini

COPY containers/monitor/settings.monitor /mist.monitor/settings.py

COPY containers/monitor/supervisord.conf /etc/supervisord.conf

EXPOSE 80

EXPOSE 25826/udp
