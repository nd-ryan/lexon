#!/bin/bash

# Doctrine Search Test Runner
# This script runs the comparison test between manual Cypher queries and AI Agent search

echo "🧪 Starting Doctrine Search Comparison Test..."
echo "=============================================="

# Check for .env file and load it
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env"
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "⚠️  No .env file found. Using system environment variables."
fi

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "✅ Activating virtual environment..."
    source venv/bin/activate
else
    echo "⚠️  No virtual environment found. Running with system Python."
fi

# Check if required dependencies are installed
echo "📦 Checking dependencies..."
python -c "import app.lib.neo4j_client, app.routes.ai" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ Dependencies available"
else
    echo "❌ Dependencies missing. Please ensure the app is properly set up."
    exit 1
fi

# Run the test
echo "🚀 Running doctrine search test..."
python test_doctrine_search.py

echo ""
echo "✅ Test completed!"
echo "Check the output above for results and any generated JSON files." 