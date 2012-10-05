"""Configuration file"""


# Choose which monitoring backend to use to get stats from
BACKEND = 'mongodb' # or 'graphite' or 'dummy'


MONGODB = {
    'host': 'localhost',
    'port': 27017,
    'dbname': 'collectd'
}


GRAPHITE = {
    'host': 'experiment.unweb.me',
    'port': 8080
}
