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
    # Update the .env file in the shared volume
    # This uses sed to replace the ST2_API_KEY line in /poundcake/.env
    sed -i "s/^ST2_API_KEY=.*/ST2_API_KEY=$NEW_KEY/" /poundcake/.env
    echo "PoundCake .env updated."
else
    echo "Failed to generate API Key."
    exit 1
fi
