#!/bin/bash
# Script to update DNS records for an agent

# Parameters
DOMAIN=$1
HOST=$2
PORT=$3
CAPABILITIES=$4
DESCRIPTION=$5
IP_ADDRESS=$6
A2A_CARD_PATH=$7     # ACDP 1.1: path of the A2A Agent Card, e.g. /.well-known/agent-card.json
PROTOCOLS=$8         # ACDP 1.1: e.g. a2a/0.3,rest-json
VERSION=${9:-1.0}    # ACDP protocol version
KEY=${10}            # ACDP arena: base64url SHA-256 fingerprint of the Ed25519 key
ZONE=${11:-agents.local}

# Default IP if not provided
if [ -z "$IP_ADDRESS" ]; then
    # Try to resolve the hostname
    IP_ADDRESS=$(dig +short $HOST)
    
    # If that fails, use localhost
    if [ -z "$IP_ADDRESS" ]; then
        IP_ADDRESS="127.0.0.1"
    fi
fi

# Ensure required parameters are provided
if [ -z "$DOMAIN" ] || [ -z "$HOST" ] || [ -z "$PORT" ]; then
    echo "Usage: $0 <domain> <host> <port> [capabilities] [description] [ip_address] [a2a_card_path] [protocols] [version]"
    echo "Example: $0 agent1.agents.local agent1.local 8000 \"chat,summarize\" \"My Agent\" 192.168.1.100"
    exit 1
fi

# Inputs are validated by dns_api.py; the TXT strings below must never contain quotes.
TXT="\"ver=$VERSION\" \"caps=$CAPABILITIES\" \"desc=$DESCRIPTION\""
if [ -n "$PROTOCOLS" ]; then
    TXT="$TXT \"proto=$PROTOCOLS\""
fi
if [ -n "$A2A_CARD_PATH" ]; then
    TXT="$TXT \"a2a=$A2A_CARD_PATH\""
fi
if [ -n "$KEY" ]; then
    TXT="$TXT \"key=$KEY\""
fi

# Create a temporary file for nsupdate commands
NSUPDATE_FILE=$(mktemp)

cat > $NSUPDATE_FILE << NSUPDATE_EOF
server localhost
zone $ZONE
update delete $DOMAIN A
update delete _llm-agent._tcp.$DOMAIN SRV
update delete _llm-agent._tcp.$DOMAIN TXT
update add $DOMAIN 300 A $IP_ADDRESS
update add _llm-agent._tcp.$DOMAIN 300 SRV 0 0 $PORT ${HOST%.}.
update add _llm-agent._tcp.$DOMAIN 300 TXT $TXT
send
NSUPDATE_EOF

# Execute nsupdate using the temporary file
nsupdate $NSUPDATE_FILE
RESULT=$?

# Clean up
rm $NSUPDATE_FILE

# Check result
if [ $RESULT -eq 0 ]; then
    echo "DNS records updated successfully for $DOMAIN"
else
    echo "Failed to update DNS records for $DOMAIN"
    exit 1
fi