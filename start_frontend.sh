#!/bin/bash

# Quick start script for frontend

cd frontend

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "❌ node_modules not found. Please run ./setup_local_macos.sh first"
    exit 1
fi

# Check if .env.local exists
if [ ! -f ".env.local" ]; then
    echo "❌ .env.local file not found. Please run ./setup_local_macos.sh first"
    exit 1
fi

echo "🚀 Starting LinkedOmicsChat frontend..."
echo "📍 Frontend will run at: http://localhost:3000"
echo ""

# Bind to all interfaces when NEXT_HOSTNAME is set (allows LAN access)
HOSTNAME_FLAG=""
if [ -n "$NEXT_HOSTNAME" ]; then
    HOSTNAME_FLAG="--hostname $NEXT_HOSTNAME"
fi

# Check if BACKGROUND env var is set
if [ "$BACKGROUND" = "true" ]; then
    echo "▶️  Starting in background mode..."
    # Use nohup to ensure process survives terminal closure
    nohup npx next dev $HOSTNAME_FLAG --port 3000 > ../logs/frontend.log 2>&1 &
    FRONTEND_PID=$!
    echo "✅ Frontend started with PID: $FRONTEND_PID"
    echo "📄 Logs: logs/frontend.log"
    echo "💡 Process will survive terminal closure and sleep/wake cycles"
else
    echo "Press Ctrl+C to stop"
    echo ""
    # Start the frontend
    npx next dev $HOSTNAME_FLAG --port 3000
fi
