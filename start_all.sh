#!/bin/bash

# Start All cpgAgent Services
# This script starts both backend and frontend in the background

set -e

echo "🚀 Starting All cpgAgent Services..."
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

# Start backend in background
echo "📦 Starting Backend..."
BACKGROUND=true ./start_backend.sh
sleep 2

echo ""

# Start frontend in background
echo "🎨 Starting Frontend..."
BACKGROUND=true ./start_frontend.sh
sleep 3

echo ""
echo "======================================"
echo "✅ All services started successfully!"
echo ""
echo "📍 Access points:"
echo "   - Frontend: http://localhost:3000"
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
