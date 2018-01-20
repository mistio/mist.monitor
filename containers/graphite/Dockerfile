FROM alpine:3.7
MAINTAINER mist.io <support@mist.io>

RUN apk add --update --no-cache python py-pip py2-cairo py2-crypto \
                                tzdata supervisor openssl ca-certificates \
                                build-base cairo-dev python-dev \
                                uwsgi uwsgi-python nginx

RUN pip install whisper==1.1.1

RUN pip install carbon==1.1.1 & \
    pip install graphite-web==1.1.1

ADD storage-schemas.conf /opt/graphite/conf/storage-schemas.conf

ADD local_settings.py /opt/graphite/webapp/graphite/local_settings.py

ADD carbon.conf /opt/graphite/conf/carbon.conf

RUN PYTHONPATH=/opt/graphite/webapp django-admin.py migrate --settings=graphite.settings --run-syncdb

ENV DJANGO_SETTINGS_MODULE graphite.settings

ADD graphite-web.sh /graphite-web.sh

ADD carbon-cache.sh /carbon-cache.sh

ADD supervisord.conf /etc/supervisord.conf

ADD nginx.conf /etc/nginx/nginx.conf

EXPOSE 2004 2003 80
