#!/bin/bash
# Quick StackStorm Diagnostic Script

echo "================================================"
echo "PoundCake StackStorm Diagnostics"
echo "================================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}✗${NC} docker-compose not found"
    exit 1
fi

# 1. Container Status
echo "1. Checking ST2 Container Status..."
echo "-----------------------------------"
ST2_CONTAINERS=$(docker-compose ps | grep st2 | awk '{print $1, $4}')
if [ -z "$ST2_CONTAINERS" ]; then
    echo -e "${RED}✗${NC} No ST2 containers found"
else
    echo "$ST2_CONTAINERS"
fi
echo ""

# 2. ST2 API Container Specific
echo "2. Checking ST2 API Container..."
echo "-----------------------------------"
ST2_API_STATUS=$(docker-compose ps st2api | grep st2api | awk '{print $4}')
if [ "$ST2_API_STATUS" == "Up" ]; then
    echo -e "${GREEN}✓${NC} st2api container is running"
else
    echo -e "${RED}✗${NC} st2api container is NOT running: $ST2_API_STATUS"
fi
echo ""

# 3. Recent Errors in ST2 API Logs
echo "3. Checking ST2 API Logs for Errors..."
echo "-----------------------------------"
ST2_ERRORS=$(docker-compose logs st2api --tail=50 2>/dev/null | grep -iE "error|fail|exception" | head -10)
if [ -z "$ST2_ERRORS" ]; then
    echo -e "${GREEN}✓${NC} No obvious errors in recent logs"
else
    echo -e "${YELLOW}⚠${NC} Found errors:"
    echo "$ST2_ERRORS"
fi
echo ""

# 4. Check Dependencies
echo "4. Checking Dependencies..."
echo "-----------------------------------"

# MariaDB
if docker-compose exec -T mariadb mysqladmin ping -uroot -prootpassword &> /dev/null; then
    echo -e "${GREEN}✓${NC} MariaDB is responding"
else
    echo -e "${RED}✗${NC} MariaDB is not responding"
fi

# RabbitMQ
if docker-compose ps rabbitmq | grep -q "Up"; then
    echo -e "${GREEN}✓${NC} RabbitMQ container is running"
else
    echo -e "${RED}✗${NC} RabbitMQ container is not running"
fi

# Redis
if docker-compose exec -T redis redis-cli ping &> /dev/null; then
    echo -e "${GREEN}✓${NC} Redis is responding"
else
    echo -e "${RED}✗${NC} Redis is not responding"
fi
echo ""

# 5. Network Connectivity
echo "5. Checking Network Connectivity..."
echo "-----------------------------------"
if docker-compose exec -T st2api curl -s http://localhost:9101/v1 &> /dev/null; then
    echo -e "${GREEN}✓${NC} ST2 API responds internally"
else
    echo -e "${RED}✗${NC} ST2 API does not respond internally"
fi

if curl -s http://localhost:9101/v1 &> /dev/null; then
    echo -e "${GREEN}✓${NC} ST2 API accessible from host"
else
    echo -e "${RED}✗${NC} ST2 API not accessible from host"
fi
echo ""

# 6. Check if ST2 is initializing
echo "6. Checking ST2 Initialization..."
echo "-----------------------------------"
INIT_LOGS=$(docker-compose logs st2api --tail=20 2>/dev/null | grep -iE "starting|initialized|ready")
if [ -z "$INIT_LOGS" ]; then
    echo -e "${YELLOW}⚠${NC} No initialization messages found"
else
    echo "$INIT_LOGS"
fi
echo ""

# 7. Port Check
echo "7. Checking Port 9101..."
echo "-----------------------------------"
if lsof -i :9101 &> /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Port 9101 is in use"
    lsof -i :9101
elif netstat -tuln 2>/dev/null | grep -q 9101; then
    echo -e "${GREEN}✓${NC} Port 9101 is listening"
    netstat -tuln | grep 9101
else
    echo -e "${RED}✗${NC} Port 9101 is not in use"
fi
echo ""

# Summary and Recommendations
echo "================================================"
echo "Summary and Recommendations"
echo "================================================"
echo ""

# Count issues
ISSUE_COUNT=0

if [ "$ST2_API_STATUS" != "Up" ]; then
    echo -e "${RED}Issue 1:${NC} ST2 API container is not running"
    echo "  Fix: docker-compose up -d st2api"
    echo ""
    ((ISSUE_COUNT++))
fi

if [ -n "$ST2_ERRORS" ]; then
    echo -e "${YELLOW}Issue 2:${NC} Errors found in ST2 logs"
    echo "  Action: Review full logs with: docker-compose logs st2api"
    echo ""
    ((ISSUE_COUNT++))
fi

if ! curl -s http://localhost:9101/v1 &> /dev/null; then
    echo -e "${YELLOW}Issue 3:${NC} ST2 API not accessible"
    echo "  Possible causes:"
    echo "    - Still initializing (wait 1-2 minutes)"
    echo "    - Configuration error (check logs)"
    echo "    - Resource constraints (check 'docker stats')"
    echo ""
    echo "  Recommended actions:"
    echo "    1. Wait 2 minutes and retry"
    echo "    2. Restart: docker-compose restart st2api"
    echo "    3. Clean restart: docker-compose down && docker-compose up -d"
    echo ""
    ((ISSUE_COUNT++))
fi

if [ $ISSUE_COUNT -eq 0 ]; then
    echo -e "${GREEN}✓${NC} No major issues detected!"
    echo ""
    echo "If you're still having connection issues:"
    echo "  1. Wait 2-3 minutes for full initialization"
    echo "  2. Check: curl http://localhost:9101/v1"
    echo "  3. Review: docker-compose logs st2api --tail=100"
else
    echo "Found $ISSUE_COUNT issue(s) - follow recommendations above"
fi

echo ""
echo "For detailed troubleshooting, see: ST2_TROUBLESHOOTING.md"
echo ""
