FROM mist/alpine:3.4
MAINTAINER mist.io <support@mist.io>

RUN apk add --update --no-cache py-cairo tzdata py-crypto supervisor

ENV PYTHONPATH /opt/graphite/lib:/opt/graphite/webapp

ENV DJANGO_SETTINGS_MODULE graphite.settings

COPY requirements.txt /requirements.txt

RUN pip install -r /requirements.txt

ADD storage-schemas.conf /opt/graphite/conf/storage-schemas.conf

ADD local_settings.py /opt/graphite/webapp/graphite/local_settings.py

ADD carbon.conf /opt/graphite/conf/carbon.conf

RUN python /opt/graphite/webapp/graphite/manage.py syncdb --noinput

ADD graphite-web.sh /graphite-web.sh

ADD carbon-cache.sh /carbon-cache.sh

ADD supervisord.conf /etc/supervisord.conf

ADD entry.sh /entry.sh

EXPOSE 2004 80
