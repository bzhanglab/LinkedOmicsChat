#!/bin/bash

# LinkedOmicsChat Local Development Setup Script for macOS
# Run this script to set up your local development environment

set -e  # Exit on error

echo "🚀 LinkedOmicsChat Local Setup for macOS"
echo "===================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Check if we're on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    print_error "This script is for macOS only"
    exit 1
fi

print_info "Checking prerequisites..."

# Check Python
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
    print_success "Python $PYTHON_VERSION found"
else
    print_error "Python 3 not found. Please install: brew install python@3.11"
    exit 1
fi

# Check Node
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    print_success "Node $NODE_VERSION found"
else
    print_error "Node.js not found. Please install: brew install node@20"
    exit 1
fi

echo ""
print_info "Setting up backend..."

# Backend setup
cd backend

# Create virtual environment
if [ ! -d "venv" ]; then
    print_info "Creating Python virtual environment..."
    python3 -m venv venv
    print_success "Virtual environment created"
else
    print_success "Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
print_info "Upgrading pip..."
pip install --upgrade pip --quiet

# Install dependencies
print_info "Installing Python dependencies (this may take a few minutes)..."
pip install -r requirements.txt --quiet
print_success "Python dependencies installed"

# Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    print_info "Creating .env file..."
    cat > .env << EOF
# LLM Configuration
# Option 1: Use mock mode (no API key needed) - ENABLED BY DEFAULT
MOCK_LLM=true

# Option 2: Use OpenAI (get free credits at https://platform.openai.com/)
# OPENAI_API_KEY=sk-your-key-here
# MOCK_LLM=false

# Database
DATABASE_URL=sqlite:///./linkedomicsai.db
REDIS_URL=redis://localhost:6379/0

# Application
ENVIRONMENT=development
DEBUG=True
SECRET_KEY=dev-secret-key-change-in-production
CORS_ORIGINS=["http://localhost:3000"]

# Agent Settings
DEFAULT_LLM_MODEL=gpt-4-turbo-preview
DEFAULT_TEMPERATURE=0.7
MAX_TOKENS=4000
AGENT_TIMEOUT_SECONDS=300
EOF
    print_success ".env file created"
    echo ""
    print_info "📝 Mock mode enabled by default (works without API key)"
    print_info "To use real AI: Get OpenAI key and edit backend/.env"
    echo ""
else
    print_success ".env file already exists"
fi

cd ..

echo ""
print_info "Setting up frontend..."

# Frontend setup
cd frontend

# Install dependencies
if [ ! -d "node_modules" ]; then
    print_info "Installing Node dependencies (this may take a few minutes)..."
    npm install --quiet
    print_success "Node dependencies installed"
else
    print_success "Node dependencies already installed"
fi

# Create .env.local if it doesn't exist
if [ ! -f ".env.local" ]; then
    print_info "Creating .env.local file..."
    cat > .env.local << EOF
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
EOF
    print_success ".env.local file created"
else
    print_success ".env.local file already exists"
fi

cd ..

echo ""
echo "=========================================="
print_success "Setup complete! 🎉"
echo "=========================================="
echo ""
echo "📝 Next steps:"
echo ""
echo "1. Add your OpenAI API key to backend/.env"
echo "   Edit: backend/.env"
echo "   Change: OPENAI_API_KEY=your-openai-key-here-CHANGE-THIS"
echo ""
echo "2. Start the backend (Terminal 1):"
echo "   cd backend"
echo "   source venv/bin/activate"
echo "   python main.py"
echo ""
echo "3. Start the frontend (Terminal 2):"
echo "   cd frontend"
echo "   npm run dev"
echo ""
echo "4. Open your browser:"
echo "   http://localhost:3000"
echo ""
echo "💡 Tips:"
echo "   - Backend runs on: http://localhost:8000"
echo "   - API docs at: http://localhost:8000/docs"
echo "   - See docs/LOCAL_DEVELOPMENT_MACOS.md for detailed guide"
echo ""
echo "Need help? Check the documentation in the docs/ folder"
echo ""
