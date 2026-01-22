#!/bin/bash

# Stop cpgAgent Backend Server
# This script stops the FastAPI backend server

set -e

echo "🛑 Stopping cpgAgent Backend..."
echo "=================================="

# Find and kill the backend process
if lsof -ti:8000 > /dev/null 2>&1; then
    echo "✓ Found backend running on port 8000"
    lsof -ti:8000 | xargs kill -9
    echo "✅ Backend stopped successfully"
else
    echo "ℹ Backend is not running on port 8000"
fi

# Alternative: Kill by process name
if pgrep -f "python.*main.py" > /dev/null; then
    echo "✓ Found backend process by name"
    pkill -f "python.*main.py"
    echo "✅ Backend process stopped"
fi

echo ""
echo "✅ Backend shutdown complete"
