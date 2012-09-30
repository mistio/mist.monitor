"""Routes and create the wsgi app"""
from logging import getLogger

from pyramid.config import Configurator

from mist.monitor.resources import Root

log = getLogger('mist.core')


def main(global_config, **settings):
    config = Configurator(root_factory=Root, settings=settings)
    config.scan()

    config.add_route('machines','/machines')
    config.add_route('machine','/machines/{machine}')

    app = config.make_wsgi_app()
    return app

