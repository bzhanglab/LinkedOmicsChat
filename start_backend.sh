#!/bin/bash

# Quick start script for backend

cd backend

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Please run ./setup_local_macos.sh first"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found. Please run ./setup_local_macos.sh first"
    exit 1
fi

# Check mode (mock or real API)
if grep -q "MOCK_LLM=true" .env; then
    echo "🎭 Running in MOCK MODE (no API key needed)"
    echo "   AI responses will be simulated for testing"
    echo ""
elif grep -q "USE_OLLAMA=true" .env; then
    echo "🦙 Running with Ollama (local LLM)"
    ollama_model=$(grep "OLLAMA_MODEL=" .env | cut -d'=' -f2)
    echo "   Model: ${ollama_model:-llama3}"
    echo ""
elif grep -q "OPENAI_API_KEY=sk-" .env; then
    echo "🤖 Running with OpenAI API"
    echo ""
else
    echo "⚠️  WARNING: No OpenAI API key found and mock mode not enabled"
    echo ""
    echo "Options:"
    echo "1. Use mock mode (no API key): Edit .env and set MOCK_LLM=true"
    echo "2. Add OpenAI key: Edit .env and add OPENAI_API_KEY=sk-xxx"
    echo "3. Install Ollama: See docs/DEVELOPMENT_WITHOUT_OPENAI.md"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "🚀 Starting cpgAgent backend..."
echo "📍 Backend will run at: http://localhost:8000"
echo "📖 API docs at: http://localhost:8000/docs"
echo ""

# Check if BACKGROUND env var is set
if [ "$BACKGROUND" = "true" ]; then
    echo "▶️  Starting in background mode..."
    # Use nohup to ensure process survives terminal closure
    nohup python main.py > ../logs/backend.log 2>&1 &
    BACKEND_PID=$!
    echo "✅ Backend started with PID: $BACKEND_PID"
    echo "📄 Logs: logs/backend.log"
    echo "💡 Process will survive terminal closure and sleep/wake cycles"
else
    echo "Press Ctrl+C to stop"
    echo ""
    # Start the backend with auto-reload
    python main.py
fi
