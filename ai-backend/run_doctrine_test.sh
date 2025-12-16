#!/bin/bash

# Doctrine Search Test Runner
# This script runs:
# - a direct Doctrine Cypher query shape check
# - (optionally) the full SearchFlow end-to-end test (LLM + Neo4j MCP)

echo "🧪 Starting Doctrine Search Comparison Test..."
echo "=============================================="

# Check for .env file and load it
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env"
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "⚠️  No .env file found. Using system environment variables."
fi

# Prefer Poetry if available (this repo is Poetry-first)
if command -v poetry >/dev/null 2>&1; then
    echo "✅ Using Poetry: $(poetry --version)"
    RUNNER="poetry run"
else
    echo "⚠️  Poetry not found. Falling back to local venv/system python."
    # Try common venv locations
    if [ -f ".venv/bin/activate" ]; then
        echo "✅ Activating .venv..."
        source .venv/bin/activate
    elif [ -f "venv/bin/activate" ]; then
        echo "✅ Activating venv..."
        source venv/bin/activate
    else
        echo "⚠️  No virtual environment found. Using system Python."
    fi
    RUNNER=""
fi

# Check if required dependencies are installed (best-effort)
echo "📦 Checking dependencies..."
${RUNNER} python -c "import app.lib.neo4j_client, app.lib.mcp_integration" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ Dependencies missing. From ai-backend/, run: poetry install"
    exit 1
fi

echo "🚀 Running direct Doctrine query shape check..."
${RUNNER} pytest -m integration -v tests/test_doctrine_query_integration.py

echo ""
echo "ℹ️  Optional: full SearchFlow end-to-end (requires OPENAI_API_KEY and RUN_SEARCH_FLOW_INTEGRATION=1)"
echo "   RUN_SEARCH_FLOW_INTEGRATION=1 ${RUNNER} pytest -m integration -v tests/test_search_flow_integration.py"

echo ""
echo "✅ Test completed!"
echo "Check the output above for results."