"""Define routes and create the wsgi app"""

import logging

from pyramid.config import Configurator

from mist.monitor.resources import Root

log = logging.getLogger(__name__)


def main(global_config, **settings):

    config = Configurator(root_factory=Root, settings=settings)
    config.scan()

    config.add_route('machines','/machines')
    config.add_route('machine','/machines/{machine}')
    config.add_route('loadavg','/machines/{machine}/loadavg')
    config.add_route('stats','/machines/{machine}/stats')
    config.add_route('rules','/machines/{machine}/rules')

    app = config.make_wsgi_app()
    return app

