#!/bin/sh

supervisord -c /etc/supervisord.conf

echo "======================"
echo "Finished and ready to run"
echo "======================"

sleep 2

supervisorctl status

/bin/sh
