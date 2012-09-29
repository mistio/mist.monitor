import os
from subprocess import call

from pyramid.view import view_config
from pyramid.response import Response


@view_config(route_name='machines', request_method='GET', renderer='json')
def list_machines(request):
    file = open(os.getcwd()+'/conf/collectd.machines')
    machines = file.read().split('\n')
    return machines


@view_config(route_name='machines', request_method='PUT', renderer='json')
def add_machine(request):
    """ add machine to monitored list """

    # get request params
    uuid = request.params.get('uuid', None)
    passwd = request.params.get('passwd', None)

    # check for errors
    if not uuid or not passwd:
        return Response('Unauthorized', 401)

    # check if uuid already in pass file
    f = open("conf/collectd.machines")
    res = f.read()
    f.close()
    if uuid in res:
        return Response('Conflict', 409)

    # append collectd pw file
    f = open("conf/collectd.machines", 'a')
    f.writelines(['\n'+ uuid + ': ' + passwd])
    f.close()


    # create new collectd conf section for allowing machine stats
    config_append = """
        PreCacheChain "%sRule"
        <Chain "%sRule">
            <Rule "rule">
                <Match "regex">
                    Host "^%s$"
                </Match>
                Target return
            </Rule>
            Target stop
        </Chain>""" % (uuid, uuid, uuid)

    f = open("conf/collectd_%s.conf"%uuid,"w")
    f.write(config_append)
    f.close()

    # include the new file in the main config
    config_include = "conf/collectd_%s.conf" % uuid
    f = open("conf/collectd.conf", "a")
    f.writelines(['\ninclude "%s"'% config_include])
    f.close()

    call(['/usr/bin/pkill','-HUP','collectd'])

    return {}
