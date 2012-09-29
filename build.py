import os
from subprocess import call

def mongoc(options, buildout, env):
    makefile_path = options['compile-directory'] + '/' + \
                os.listdir(options['compile-directory'])[0] + '/Makefile'
    intcheck_path = options['compile-directory'] + '/' + \
                os.listdir(options['compile-directory'])[0] + '/check_int64.sh'
    os.chmod(intcheck_path,0500)
    makefile = open(makefile_path)
    content = makefile.read()
    makefile.close()
    content = content.replace('/usr/local', options['prefix'])
    os.mkdir(options['prefix']+'/lib')
    os.mkdir(options['prefix']+'/include')
    makefile = open(makefile_path,'w')
    makefile.write(content)
    makefile.close()


def collectd(options, buildout, env):
    buildfile_path = options['compile-directory'] + '/' + \
                os.listdir(options['compile-directory'])[0] + '/build.sh'
    versiongen_path = options['compile-directory'] + '/' + \
                os.listdir(options['compile-directory'])[0] + '/version-gen.sh'                
    os.chmod(buildfile_path,0500)
    os.chmod(versiongen_path,0500)
    call(buildfile_path)
