#!/bin/bash

# Stop All LinkedOmicsChat Services
# This script stops both backend and frontend servers

set -e

echo "🛑 Stopping All LinkedOmicsChat Services..."
echo "======================================"
echo ""

# Stop Ollama if it was started by us
if [ -f "logs/ollama.log" ]; then
    echo "🦙 Stopping Ollama..."
    if lsof -ti:11434 > /dev/null 2>&1; then
        lsof -ti:11434 | xargs kill -9 2>/dev/null || true
        echo "   ✅ Ollama stopped"
    else
        echo "   ℹ Ollama is not running"
    fi
    echo ""
fi

# Stop backend
./stop_backend.sh

echo ""

# Stop frontend
./stop_frontend.sh

echo ""
echo "✅ All services stopped successfully!"
