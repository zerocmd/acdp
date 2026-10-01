#!/bin/bash
# Start BIND with rndc enabled, then the DNS API.
# named runs as user bind. It needs write access to the zone and log directories.
set -e
[ -f /etc/bind/rndc.key ] || rndc-confgen -a -c /etc/bind/rndc.key
mkdir -p /var/cache/bind/zones /var/log/named
chown -R bind:bind /var/cache/bind /var/log/named /etc/bind/zones /etc/bind/rndc.key
named -g -u bind -c /etc/bind/named.conf &
exec python3 /usr/local/bin/dns_api.py
