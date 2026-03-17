#!/bin/bash

# Start All LinkedOmicsChat Services
# This script starts both backend and frontend in the background

set -e

echo "🚀 Starting All LinkedOmicsChat Services..."
echo "======================================"
echo ""

# Create logs directory if it doesn't exist
mkdir -p logs

# Check if Ollama is needed and start it
if [ -f "backend/.env" ] && grep -q "USE_OLLAMA=true" backend/.env; then
    echo "🦙 Checking Ollama..."
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "   Starting Ollama server..."
        ollama serve > logs/ollama.log 2>&1 &
        OLLAMA_PID=$!
        echo "   ✅ Ollama started with PID: $OLLAMA_PID"
        echo "   📄 Logs: logs/ollama.log"
        sleep 2  # Give Ollama time to start
    else
        echo "   ✅ Ollama is already running"
    fi
    echo ""
fi

# Detect local network IP and write frontend .env.local
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null \
    || ipconfig getifaddr en1 2>/dev/null \
    || ipconfig getifaddr en2 2>/dev/null \
    || ifconfig | awk '/inet / && !/127\.0\.0\.1/ && !/169\.254\./ {print $2; exit}')

if [ -n "$LOCAL_IP" ]; then
    echo "🌐 Detected network IP: $LOCAL_IP"

    # Update frontend/.env.local so API calls go to the correct host
    cat > frontend/.env.local <<EOF
NEXT_PUBLIC_API_URL=http://${LOCAL_IP}:8000
EOF
    echo "   Updated frontend/.env.local → NEXT_PUBLIC_API_URL=http://${LOCAL_IP}:8000"

    # Update backend CORS_ORIGINS to allow requests from the network IP
    CORS_VALUE="[\"http://localhost:3000\",\"http://localhost:3001\",\"http://${LOCAL_IP}:3000\"]"
    if [ -f "backend/.env" ]; then
        if grep -q "^CORS_ORIGINS=" backend/.env; then
            sed -i '' "s|^CORS_ORIGINS=.*|CORS_ORIGINS=${CORS_VALUE}|" backend/.env
        else
            echo "CORS_ORIGINS=${CORS_VALUE}" >> backend/.env
        fi
        echo "   Updated backend/.env       → CORS_ORIGINS includes http://${LOCAL_IP}:3000"
    fi
else
    echo "⚠️  Could not detect local IP — keeping existing .env.local and CORS settings"
fi
echo ""

# Start backend in background
echo "📦 Starting Backend..."
BACKGROUND=true ./start_backend.sh
sleep 2

echo ""

# Start frontend in background (bind to all interfaces so LAN devices can connect)
echo "🎨 Starting Frontend..."
BACKGROUND=true NEXT_HOSTNAME=0.0.0.0 ./start_frontend.sh
sleep 3

echo ""
echo "======================================"
echo "✅ All services started successfully!"
echo ""

# Check if MCP is enabled
if [ -f "backend/.env" ] && grep -q "USE_MCP=true" backend/.env; then
    echo "🔌 MCP Architecture: ENABLED"
    echo "   Check backend logs for MCP tool discovery"
    echo ""
fi

echo "📍 Access points:"
echo "   - Local:    http://localhost:3000"
if [ -n "$LOCAL_IP" ]; then
    echo "   - Network:  http://${LOCAL_IP}:3000  (phone / other devices)"
fi
echo "   - Backend:  http://localhost:8000"
echo "   - API docs: http://localhost:8000/docs"
echo ""
echo "📄 Log files:"
if [ -f "backend/.env" ] && grep -q "USE_OLLAMA=true" backend/.env; then
    echo "   - Ollama:   logs/ollama.log"
fi
echo "   - Backend:  logs/backend.log"
echo "   - Frontend: logs/frontend.log"
echo ""
echo "🛑 To stop all services, run: ./stop_all.sh"
echo ""
echo "💡 Monitor logs:"
echo "   - Backend:  tail -f logs/backend.log"
echo "   - Frontend: tail -f logs/frontend.log"
echo ""
