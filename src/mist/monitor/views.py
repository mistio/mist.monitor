import os
import logging
import traceback
from subprocess import call
from time import time

from pyramid.view import view_config
from pyramid.response import Response

from mist.monitor import config
from mist.monitor import methods
from mist.monitor import graphite

from mist.monitor.model import get_all_machines

from mist.monitor.exceptions import MistError
from mist.monitor.exceptions import RequiredParameterMissingError
from mist.monitor.exceptions import MachineNotFoundError
from mist.monitor.exceptions import ForbiddenError
from mist.monitor.exceptions import UnauthorizedError


log = logging.getLogger(__name__)
OK = Response("OK", 200)


@view_config(context=Exception)
def exception_handler_mist(exc, request):
    """Here we catch exceptions and transform them to proper http responses

    This is a special pyramid view that gets triggered whenever an exception
    is raised from any other view. It catches all exceptions exc where
    isinstance(exc, context) is True.

    """

    # non-mist exceptions. that shouldn't happen! never!
    if not isinstance(exc, MistError):
        trace = traceback.format_exc()
        log.critical("Uncaught non-mist exception? WTF!\n%s", trace)
        return Response("Internal Server Error", 500)

    # mist exceptions are ok.
    log.info("MistError: %r", exc)

    # translate it to HTTP response based on http_code attribute
    return Response(str(exc), exc.http_code)


@view_config(route_name='machines', request_method='GET', renderer='json')
def list_machines(request):
    """Lists machines with monitoring.

    Returns a dict with uuid's as keys and machine dicts as values.

    """
    return {machine.uuid: machine.as_dict() for machine in get_all_machines()}


@view_config(route_name='machines', request_method='PUT')
def add_machine(request):
    """Adds machine to monitored list."""
    uuid = request.params.get('uuid')
    passwd = request.params.get('passwd')
    log.info("Adding machine %s to monitor list" % (uuid))

    if not uuid:
        raise RequiredParameterMissingError('uuid')
    if not passwd:
        raise RequiredParameterMissingError('passwd')

    methods.add_machine(uuid, passwd)

    return OK


@view_config(route_name='machine', request_method='DELETE')
def remove_machine(request):
    """Removes machine from monitored list."""
    uuid = request.matchdict['machine']
    log.info("Removing machine %s from monitor list" % (uuid))

    machine = get_machine_from_uuid(uuid)
    if not machine:
        raise MachineNotFoundError(uuid)

    methods.remove_machine(uuid)
    return OK


@view_config(route_name='rules', request_method='PUT', renderer='json')
def update_rules(request):

    params = request.json_body
    action = params.get('rule_action')  #FIXME: use different HTTP method ffs!
    uuid = params.get("uuid")
    rule_id = params.get("rule_id")

    if action == 'add':
        metric = params.get("metric")
        operator = params.get("operator")
        value = params.get("value")
        time_to_wait = params.get("time_to_wait")
        if metric in ['network-tx', 'disk-write']:
            value = float(value) * 1000
        methods.update_rule(uuid, rule_id, metric, operator, value, time_to_wait)
    else:
        methods.remove_rule(uuid, rule_id)

    return OK


@view_config(route_name='stats', request_method='GET', renderer='json')
def get_stats(request):
    """Returns all stats for a machine, the client will draw them."""

    uuid = request.matchdict['machine']
    params = request.params
    allowed_targets = ['cpu', 'load', 'memory', 'disk', 'network']
    expression = params.get('expression',
                            ['cpu', 'load', 'memory', 'disk', 'network'])
    start = int(params.get('start', 0))
    stop = int(params.get('stop', 0))

    if isinstance(expression, basestring):
        expression = expression.split(',')
    for target in expression:
        if target not in allowed_targets:
            raise BadRequestError("Bad target '%.s'" % target)

    return methods.get_stats(uuid, expression, start, stop)


@view_config(route_name='reset', request_method='PUT')
def reset_hard(request):
    params = request.json_body
    key, data = params.get('key'), params.get('data', {})
    if not config.RESET_KEY:
        raise ForbiddenError("Reset functionality not enabled.")
    if key != config.RESET_KEY:
        raise UnauthorizedError("Wrong reset key provided.")
    methods.reset_hard(params['data'])
    return OK
