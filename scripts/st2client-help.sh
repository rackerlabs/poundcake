#!/bin/bash
# ST2 Client Troubleshooting Helper
# Quick reference for using the st2client container

echo "========================================="
echo "  ST2 Client Troubleshooting Commands"
echo "========================================="
echo ""
echo "The st2client container is available for interactive StackStorm operations."
echo "Use it to debug, test actions, and manage packs."
echo ""

echo "📋 Common Operations:"
echo ""

echo "1️⃣  Interactive Shell Access"
echo "   docker compose exec st2client bash"
echo ""

echo "2️⃣  List All Packs"
echo "   docker compose exec st2client st2 pack list"
echo ""

echo "3️⃣  List Core Actions"
echo "   docker compose exec st2client st2 action list --pack=core"
echo ""

echo "4️⃣  Run a Test Command"
echo "   docker compose exec st2client st2 run core.local cmd=\"echo 'Hello from ST2'\""
echo ""

echo "5️⃣  Check Pack Installation"
echo "   docker compose exec st2client st2 pack show core"
echo ""

echo "6️⃣  Install a New Pack"
echo "   docker compose exec st2client st2 pack install <pack-name>"
echo ""

echo "7️⃣  Get Authentication Token"
echo "   docker compose exec st2client st2 auth st2admin -p Ch@ngeMe"
echo ""

echo "8️⃣  View Pack Actions"
echo "   docker compose exec st2client st2 action list --pack=<pack-name>"
echo ""

echo "9️⃣  Execute an Action"
echo "   docker compose exec st2client st2 run <pack>.<action> <parameters>"
echo ""

echo "🔟 View Action Executions"
echo "   docker compose exec st2client st2 execution list"
echo ""

echo "========================================="
echo "  Advanced Troubleshooting"
echo "========================================="
echo ""

echo "🔍 Check StackStorm API Connectivity"
echo "   docker compose exec st2client curl -s http://stackstorm-api:9101/v1 | jq ."
echo ""

echo "🔍 Check Authentication Service"
echo "   docker compose exec st2client curl -s http://stackstorm-auth:9100 | jq ."
echo ""

echo "🔍 View Packs Directory"
echo "   docker compose exec st2client ls -la /opt/stackstorm/packs/"
echo ""

echo "🔍 Check Core Pack Contents"
echo "   docker compose exec st2client ls -la /opt/stackstorm/packs/core/"
echo ""

echo "🔍 Test Direct Python Execution"
echo "   docker compose exec st2client /opt/stackstorm/st2/bin/python3 -m st2common.bin.st2_run_local core.local cmd=\"echo 'test'\""
echo ""

echo "🔍 Re-register Content (if needed)"
echo "   docker compose exec st2client st2-register-content --register-all --setup-virtualenvs --config-file /etc/st2/st2.conf"
echo ""

echo "========================================="
echo "  Service Status"
echo "========================================="
echo ""

# Check if st2client is running
if docker compose ps st2client 2>/dev/null | grep -q "Up"; then
    echo "✅ st2client is running and ready"
    echo ""
    echo "Quick test:"
    echo "----------"
    if docker compose exec -T st2client st2 pack list >/dev/null 2>&1; then
        echo "✅ ST2 CLI is working"
        PACK_COUNT=$(docker compose exec -T st2client st2 pack list 2>/dev/null | tail -n +4 | wc -l)
        echo "📦 $PACK_COUNT packs registered"
    else
        echo "⚠️  ST2 CLI test failed - check logs:"
        echo "   docker compose logs st2client"
    fi
else
    echo "❌ st2client is not running"
    echo ""
    echo "Start it with:"
    echo "   docker compose up -d st2client"
fi

echo ""
echo "========================================="
echo "  Bootstrap Status"
echo "========================================="
echo ""

# Check bootstrap status
if docker compose ps stackstorm-bootstrap 2>/dev/null | grep -q "Exited (0)"; then
    echo "✅ stackstorm-bootstrap completed successfully"
elif docker compose ps stackstorm-bootstrap 2>/dev/null | grep -q "Up"; then
    echo "⏳ stackstorm-bootstrap is still running"
    echo "   Watch logs: docker compose logs -f stackstorm-bootstrap"
else
    echo "⚠️  stackstorm-bootstrap may have failed"
    echo "   Check logs: docker compose logs stackstorm-bootstrap"
    echo "   View status: docker compose ps stackstorm-bootstrap"
fi

echo ""
echo "========================================="
echo "  Example Workflow"
echo "========================================="
echo ""
echo "# 1. Enter interactive shell"
echo "docker compose exec st2client bash"
echo ""
echo "# 2. Inside the container, authenticate"
echo "st2 auth st2admin -p Ch@ngeMe"
echo ""
echo "# 3. List available actions"
echo "st2 action list"
echo ""
echo "# 4. Run a test command"
echo "st2 run core.local cmd=\"whoami\""
echo ""
echo "# 5. View execution history"
echo "st2 execution list -n 5"
echo ""
echo "# 6. Exit the container"
echo "exit"
echo ""

echo "For more information:"
echo "  - StackStorm Docs: https://docs.stackstorm.com/"
echo "  - ST2 CLI Reference: https://docs.stackstorm.com/reference/cli.html"
echo ""
