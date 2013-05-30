"""Routes and create the wsgi app"""
from logging import getLogger

from pyramid.config import Configurator

from mist.monitor.resources import Root

log = getLogger('mist.monitor')


def main(global_config, **settings):

    # Import settings from settings.py
    user_config = {}
    execfile(global_config['here'] + '/settings.py', user_config)

    settings['backend'] = user_config['BACKEND']
    settings['core'] = user_config['CORE_URI']

    config = Configurator(root_factory=Root, settings=settings)
    config.scan()

    config.add_route('machines','/machines')
    config.add_route('machine','/machines/{machine}')
    config.add_route('loadavg','/machines/{machine}/loadavg')
    config.add_route('stats','/machines/{machine}/stats')
    config.add_route('rules','/machines/{machine}/rules')

    app = config.make_wsgi_app()
    return app

