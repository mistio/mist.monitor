.. contents::

Introduction
============

Install
============
$ sudo aptitude install python-dev flex yacc autoheader automake autoconf libtool bison automake autoconf libtool pkg-config libgcrypt11-dev libperl-dev librrd-dev
$ python bootstrap.py
$ ./bin/buildout


graphite is installed, just needs syncdb to be run manually
$ ./bin/graphite syncdb --settings=graphite.settings

(install collectd-graphite by hand as explained here:https://github.com/joemiller/collectd-graphite)

Start supervisord with sudo (collectd requires root)

