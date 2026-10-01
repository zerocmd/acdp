#!/bin/bash
# Create a primary zone at run time. dns_api.py validates the zone name.
set -euo pipefail

ZONE=$1
ZONE_DIR=${2:-/var/cache/bind/zones}
FILE="$ZONE_DIR/db.$ZONE"

mkdir -p "$ZONE_DIR"
if [ -f "$FILE" ]; then
    echo "exists"
    exit 0
fi

cat > "$FILE" <<ZONE_EOF
\$TTL 300
@       IN      SOA     ns.$ZONE. admin.$ZONE. ( 1 300 60 604800 300 )
@       IN      NS      ns.$ZONE.
ns      IN      A       127.0.0.1
ZONE_EOF
chown bind:bind "$ZONE_DIR" "$FILE" 2>/dev/null || true

if ! rndc addzone "$ZONE" "{ type primary; file \"$FILE\"; allow-update { any; }; };"; then
    rm -f "$FILE"
    exit 1
fi
echo "created"
