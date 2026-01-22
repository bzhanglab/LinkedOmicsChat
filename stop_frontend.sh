#!/bin/bash

# Stop cpgAgent Frontend Server
# This script stops the Next.js development server

set -e

echo "🛑 Stopping cpgAgent Frontend..."
echo "=================================="

# Find and kill the frontend process
if lsof -ti:3000 > /dev/null 2>&1; then
    echo "✓ Found frontend running on port 3000"
    lsof -ti:3000 | xargs kill -9
    echo "✅ Frontend stopped successfully"
else
    echo "ℹ Frontend is not running on port 3000"
fi

# Alternative: Kill by process name
if pgrep -f "next.*dev" > /dev/null; then
    echo "✓ Found Next.js dev server by name"
    pkill -f "next.*dev"
    echo "✅ Next.js process stopped"
fi

echo ""
echo "✅ Frontend shutdown complete"
