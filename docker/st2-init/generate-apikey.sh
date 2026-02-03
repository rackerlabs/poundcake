#!/bin/bash
# Wait for ST2 API to be ready
echo "Waiting for StackStorm API to wake up..."
until curl -s http://stackstorm-api:9101/v1/health > /dev/null; do
    sleep 2
done

echo "Authenticating as st2admin..."
# Get a temporary token
ST2_TOKEN=$(st2 auth st2admin -p 'chained-to-the-oven' -t)

if [ -z "$ST2_TOKEN" ]; then
    echo "Failed to get auth token!"
    exit 1
fi

echo "Generating API Key..."
# Create a new API key for the PoundCake API
NEW_KEY=$(st2 apikey create -p poundcake-api -t $ST2_TOKEN | grep key | awk '{print $4}')

if [ -n "$NEW_KEY" ]; then
    echo "Successfully generated key: $NEW_KEY"
    
    # Write key to shared config directory
    mkdir -p /poundcake/config
    echo "$NEW_KEY" > /poundcake/config/st2_api_key
    chmod 644 /poundcake/config/st2_api_key
    
    # Also update .env for manual reference
    sed -i "s/^ST2_API_KEY=.*/ST2_API_KEY=$NEW_KEY/" /poundcake/.env
    
    echo "API Key written to config/st2_api_key and .env updated"
    echo "PoundCake can now authenticate with StackStorm!"
else
    echo "Failed to generate API Key."
    exit 1
fi
