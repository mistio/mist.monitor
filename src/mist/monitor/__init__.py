"""Define routes and create the wsgi app"""

import logging

from pyramid.config import Configurator

from mist.monitor.resources import Root

log = logging.getLogger(__name__)


def main(global_config, **settings):

    config = Configurator(root_factory=Root, settings=settings)
    config.scan()

    config.add_route('machines', '/machines')
    config.add_route('machine', '/machines/{machine}')
    config.add_route('stats', '/machines/{machine}/stats')
    config.add_route('find_metrics', '/machines/{machine}/metrics')
    ## config.add_route('rules', '/machines/{machine}/rules')
    config.add_route('rule', '/machines/{machine}/rules/{rule}')
    config.add_route('reset', '/reset')

    config.add_route('cross_graphs', '/cross_graphs')

    app = config.make_wsgi_app()
    return app

