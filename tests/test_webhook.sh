#!/bin/bashQ
#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#          PoundCake Webhook Test Script

API_URL="http://localhost:8000"

# ... (Health Check and POST same as before) ...

echo "4. Checking alert was stored..."
# The API returns a list. We use jq for better parsing if available,
# but sticking to grep/cut for compatibility.
ALERT_CHECK=$(curl -s "$API_URL/api/v1/alerts?processing_status=new")
# Extract the first alert_name found in the JSON array
ALERT_NAME=$(echo "$ALERT_CHECK" | grep -o '"alert_name":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ "$ALERT_NAME" == "HelloWorldAlert" ]; then
    echo "    ✓ Alert found in queue!"
    echo "    - Alert name: $ALERT_NAME"
else
    echo "    ✗ Alert not found in 'new' queue"
    echo "    - Response: $ALERT_CHECK"
    exit 1
fi

echo "===================================="
echo "✓ Webhook and DB Intake passed!"
