CLUSTER_SERVERS = []

# List all local running carbon-cache instances (their cache query ports)
CARBONLINK_HOSTS = ['127.0.0.1:7002']

DASHBOARD_REQUIRE_AUTHENTICATION = False
LOG_RENDERING_PERFORMANCE = False
LOG_CACHE_PERFORMANCE = False
LOG_METRIC_ACCESS = False

STATIC_ROOT = '/opt/graphite/webapp/content/'
STATIC_URL = '/content/'

STATICFILES_DIRS = (

#    os.path.join(BASE_DIR, "static"),
#    os.path.join(BASE_DIR, "content"),
    "/opt/graphite/webapp/content/",

)

STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
)
