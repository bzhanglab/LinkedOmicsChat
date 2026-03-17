#!/bin/bash

# AWS Deployment Script for LinkedOmicsChat
# This script helps set up the application on an AWS EC2 instance

set -e

echo "🚀 LinkedOmicsChat AWS Deployment Script"
echo "=================================="
echo ""

# Check if running on EC2
if [ ! -f "/sys/class/dmi/id/product-uuid" ]; then
    echo "⚠️  Warning: This script is designed to run on an EC2 instance"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Installing Docker..."
    
    # Detect OS
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
    else
        OS=$(uname -s)
    fi
    
    if [ "$OS" = "amzn" ] || [ "$OS" = "amazon" ]; then
        # Amazon Linux installation
        echo "📦 Detected Amazon Linux - installing Docker..."
        sudo yum install -y docker
        sudo systemctl start docker
        sudo systemctl enable docker
        sudo usermod -aG docker $USER
    elif [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
        # Ubuntu/Debian installation
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        sudo usermod -aG docker $USER
    else
        # Generic installation
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        sudo usermod -aG docker $USER
    fi
    
    echo "✅ Docker installed. Please log out and back in, then run this script again."
    exit 0
fi

# Check for Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Installing..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "✅ Docker Compose installed"
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "📝 Creating .env file..."
    
    # Try multiple methods to get public IP
    PUBLIC_IP=""
    
    # Method 1: EC2 metadata service with IMDSv2 (token-based)
    if [ -z "$PUBLIC_IP" ]; then
        TOKEN=$(curl -sS -X PUT "http://169.254.169.254/latest/api/token" \
            -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null || echo "")
        if [ ! -z "$TOKEN" ]; then
            PUBLIC_IP=$(curl -sS -H "X-aws-ec2-metadata-token: $TOKEN" \
                http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "")
        fi
    fi
    
    # Method 2: EC2 metadata service IMDSv1 (fallback)
    if [ -z "$PUBLIC_IP" ]; then
        PUBLIC_IP=$(curl -s --max-time 2 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "")
    fi
    
    # Method 3: AWS CLI (if available)
    if [ -z "$PUBLIC_IP" ] && command -v aws &> /dev/null; then
        TOKEN=$(curl -sS -X PUT "http://169.254.169.254/latest/api/token" \
            -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null || echo "")
        if [ ! -z "$TOKEN" ]; then
            INSTANCE_ID=$(curl -sS -H "X-aws-ec2-metadata-token: $TOKEN" \
                http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo "")
        else
            INSTANCE_ID=$(curl -s --max-time 2 http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo "")
        fi
        if [ ! -z "$INSTANCE_ID" ]; then
            PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text 2>/dev/null || echo "")
        fi
    fi
    
    # Method 4: External service (as last resort)
    if [ -z "$PUBLIC_IP" ]; then
        PUBLIC_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || echo "")
    fi
    
    # If still no IP, prompt user
    if [ -z "$PUBLIC_IP" ]; then
        echo "⚠️  Could not auto-detect public IP"
        echo "   (Metadata service may be disabled or instance has no public IP)"
        read -p "Enter your EC2 public IP address or domain name: " PUBLIC_IP
        if [ -z "$PUBLIC_IP" ]; then
            echo "❌ IP address or domain is required"
            exit 1
        fi
    else
        echo "✅ Detected IP: $PUBLIC_IP"
        read -p "Enter your domain name (or press Enter to use IP: $PUBLIC_IP): " DOMAIN
        DOMAIN=${DOMAIN:-$PUBLIC_IP}
    fi
    
    echo ""
    echo "Choose LLM provider:"
    echo "1. Ollama (Local LLM - Free but slower, no API key needed)"
    echo "2. OpenAI (Faster but costs money, requires API key)"
    echo "3. Mock mode (for testing, no real AI)"
    echo ""
    echo "   Note: You can switch between Ollama and OpenAI later by editing .env"
    read -p "Enter choice (1-3, default: 1): " LLM_CHOICE
    LLM_CHOICE=${LLM_CHOICE:-1}
    
    USE_OLLAMA="false"
    MOCK_MODE="false"
    OPENAI_KEY=""
    ANTHROPIC_KEY=""
    OLLAMA_MODEL="llama3"
    
    case $LLM_CHOICE in
        1)
            USE_OLLAMA="true"
            read -p "Enter Ollama model name (default: llama3): " OLLAMA_MODEL_INPUT
            OLLAMA_MODEL=${OLLAMA_MODEL_INPUT:-llama3}
            echo "✅ Using Ollama with model: $OLLAMA_MODEL"
            echo "   Note: Ollama may be slower on CPU-only instances"
            echo "   To switch to OpenAI later: Edit .env (USE_OLLAMA=false, add OPENAI_API_KEY)"
            ;;
        2)
            read -p "Enter OpenAI API Key: " OPENAI_KEY
            if [ -z "$OPENAI_KEY" ]; then
                echo "❌ OpenAI API key is required"
                exit 1
            fi
            echo "✅ Using OpenAI (faster, but costs money per request)"
            echo "   To switch to Ollama later: Edit .env (USE_OLLAMA=true)"
            ;;
        3)
            MOCK_MODE="true"
            echo "✅ Using mock mode (for testing only)"
            ;;
    esac
    
    if [ "$USE_OLLAMA" = "true" ]; then
        read -p "Enter Anthropic API Key (optional, press Enter to skip): " ANTHROPIC_KEY
    fi
    
    # Generate secure passwords
    DB_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
    SECRET_KEY=$(openssl rand -base64 32)
    
    cat > .env << EOF
# Database
DB_PASSWORD=$DB_PASSWORD

# API Keys
OPENAI_API_KEY=${OPENAI_KEY:-}
ANTHROPIC_API_KEY=${ANTHROPIC_KEY:-}
USE_OLLAMA=$USE_OLLAMA
OLLAMA_MODEL=$OLLAMA_MODEL
OLLAMA_BASE_URL=http://ollama:11434
MOCK_LLM=$MOCK_MODE

# Application
ENVIRONMENT=production
DEBUG=False
SECRET_KEY=$SECRET_KEY

# CORS (comma-separated format for easier parsing)
CORS_ORIGINS=http://$DOMAIN:3000,http://$DOMAIN,http://$PUBLIC_IP:3000,http://$PUBLIC_IP

# Database URL
DATABASE_URL=postgresql://linkedomicsai:$DB_PASSWORD@postgres:5432/linkedomicsai
REDIS_URL=redis://redis:6379/0

# Frontend URLs
NEXT_PUBLIC_API_URL=http://$DOMAIN:8000
NEXT_PUBLIC_WS_URL=ws://$DOMAIN:8000
EOF
    
    echo "✅ .env file created"
    echo ""
    echo "⚠️  IMPORTANT: Update NEXT_PUBLIC_API_URL in docker-compose.yml to match your domain/IP"
else
    echo "✅ .env file already exists"
fi

# Update docker-compose.yml with correct API URL
if [ -f "docker-compose.yml" ]; then
    PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "localhost")
    read -p "Update frontend API URL in docker-compose.yml? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        read -p "Enter API URL (default: http://$PUBLIC_IP:8000): " API_URL
        API_URL=${API_URL:-"http://$PUBLIC_IP:8000"}
        
        # Update docker-compose.yml (simple sed replacement)
        if grep -q "NEXT_PUBLIC_API_URL" docker-compose.yml; then
            sed -i "s|NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=$API_URL|g" docker-compose.yml
            sed -i "s|NEXT_PUBLIC_WS_URL=.*|NEXT_PUBLIC_WS_URL=${API_URL/http/ws}|g" docker-compose.yml
            echo "✅ Updated docker-compose.yml"
        fi
    fi
fi

# Build and start services
echo ""
echo "🔨 Building and starting services..."
docker-compose up -d --build

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 10

# If using Ollama, pull the model
if [ "$USE_OLLAMA" = "true" ]; then
    echo ""
    echo "📥 Downloading Ollama model: $OLLAMA_MODEL"
    echo "   This may take several minutes depending on model size..."
    docker-compose exec -T ollama ollama pull $OLLAMA_MODEL || {
        echo "⚠️  Warning: Could not pull model automatically"
        echo "   You can manually pull it later with:"
        echo "   docker-compose exec ollama ollama pull $OLLAMA_MODEL"
    }
fi

# Check service status
echo ""
echo "📊 Service Status:"
docker-compose ps

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📝 Next steps:"
echo "1. Check logs: docker-compose logs -f"
echo "2. Access frontend: http://$DOMAIN:3000 (or configure nginx)"
echo "3. Access backend API: http://$DOMAIN:8000"
echo "4. API docs: http://$DOMAIN:8000/docs"
echo ""
echo "🔒 Security reminders:"
echo "- Update CORS_ORIGINS in .env with your actual domain"
echo "- Set up SSL/HTTPS for production"
echo "- Configure firewall rules"
echo "- Set up automated backups"
echo ""
if [ "$USE_OLLAMA" = "true" ]; then
    echo "🔄 To switch to OpenAI (faster):"
    echo "   1. Edit .env: Set USE_OLLAMA=false and add OPENAI_API_KEY=your-key"
    echo "   2. Restart: docker compose restart backend"
elif [ "$MOCK_MODE" = "false" ]; then
    echo "🔄 To switch to Ollama (free but slower):"
    echo "   1. Edit .env: Set USE_OLLAMA=true"
    echo "   2. Restart: docker compose restart backend"
    echo "   3. Pull model: docker compose exec ollama ollama pull llama3"
fi
