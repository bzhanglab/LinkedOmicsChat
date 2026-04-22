#!/bin/bash

# Rsync-based deployment script for LinkedOmicsChat
# Syncs local changes (including uncommitted) to AWS EC2 instance
# Faster than git pull - no need to commit everything
#
# SAFETY FEATURES:
# - By default, does NOT delete files on server (safe mode)
# - Preserves server-specific files (.env, databases, logs)
# - Use LINKEDOMICSCHAT_DRY_RUN=true to preview changes before syncing
# - Use LINKEDOMICSCHAT_USE_DELETE=true to enable deletion (use with caution!)
#
# PROTECTED FILES (never synced, server keeps its own):
# - .env (server configuration)
# - *.db, *.sqlite (databases)
# - node_modules/, .next/ (rebuilt in Docker)
# - logs/, *.log (server logs)
# - data/ (server data directory)

set -e

# Configuration - UPDATE THESE
# Prefer LINKEDOMICSCHAT_* variables. Legacy LINKEDOMICSAI_ / LINKEDOMICS_ /
# CPGAGENT_ aliases are still supported for backward compatibility.
LINKEDOMICSCHAT_AWS_HOST="${LINKEDOMICSCHAT_AWS_HOST:-${LINKEDOMICSAI_AWS_HOST:-${LINKEDOMICS_AWS_HOST:-${CPGAGENT_AWS_HOST:-ec2-user@your-instance-ip}}}}"  # e.g., ec2-user@1.2.3.4
LINKEDOMICSCHAT_AWS_KEY="${LINKEDOMICSCHAT_AWS_KEY:-${LINKEDOMICSAI_AWS_KEY:-${LINKEDOMICS_AWS_KEY:-${CPGAGENT_AWS_KEY:-~/.ssh/your-key.pem}}}}"                 # Path to your SSH key
LINKEDOMICSCHAT_REMOTE_PATH="${LINKEDOMICSCHAT_REMOTE_PATH:-${LINKEDOMICSAI_REMOTE_PATH:-${LINKEDOMICS_REMOTE_PATH:-${CPGAGENT_REMOTE_PATH:-~/LinkedOmicsChat}}}}"  # Path on remote server
LINKEDOMICSCHAT_SYNC_GIT="${LINKEDOMICSCHAT_SYNC_GIT:-${LINKEDOMICSAI_SYNC_GIT:-${LINKEDOMICS_SYNC_GIT:-${CPGAGENT_SYNC_GIT:-false}}}}"
LINKEDOMICSCHAT_DRY_RUN="${LINKEDOMICSCHAT_DRY_RUN:-${LINKEDOMICSAI_DRY_RUN:-${LINKEDOMICS_DRY_RUN:-${CPGAGENT_DRY_RUN:-false}}}}"
LINKEDOMICSCHAT_USE_DELETE="${LINKEDOMICSCHAT_USE_DELETE:-${LINKEDOMICSAI_USE_DELETE:-${LINKEDOMICS_USE_DELETE:-${CPGAGENT_USE_DELETE:-false}}}}"
LINKEDOMICSCHAT_SERVER_FILES="${LINKEDOMICSCHAT_SERVER_FILES:-${LINKEDOMICSAI_SERVER_FILES:-${LINKEDOMICS_SERVER_FILES:-${CPGAGENT_SERVER_FILES:-}}}}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 LinkedOmicsChat Rsync Deployment${NC}"
echo "=================================="
echo ""

# Show safety info based on mode
if [[ "${LINKEDOMICSCHAT_USE_DELETE}" == "true" ]]; then
    echo -e "${RED}⚠️  DELETE MODE ENABLED${NC}"
    echo "   - Files on server not in local WILL BE DELETED"
    echo "   - Server-specific files are protected (see below)"
else
    echo -e "${GREEN}✓  Safe Mode (default)${NC}"
    echo "   - Only adds/updates files that exist locally"
    echo "   - Files on server not in local are preserved"
fi

echo ""
echo -e "${YELLOW}ℹ️  Protected files (never synced, never deleted):${NC}"
echo "   - .env, .env.production, .env.server (server config)"
echo "   - *.db, *.sqlite (databases)"
echo "   - server-config.*, production-config.*"
echo "   - server-data/, production-data/"
echo "   - Custom files (set LINKEDOMICSCHAT_SERVER_FILES='file1,file2')"
echo ""
echo "Options:"
echo "   - LINKEDOMICSCHAT_DRY_RUN=true (preview changes)"
echo "   - LINKEDOMICSCHAT_USE_DELETE=true (enable deletion - dangerous!)"
echo "   - LINKEDOMICSCHAT_SERVER_FILES='file1,file2' (protect custom files)"
echo ""

# Check if LINKEDOMICSCHAT_AWS_HOST is set
if [[ "$LINKEDOMICSCHAT_AWS_HOST" == "ec2-user@your-instance-ip" ]]; then
    echo -e "${YELLOW}⚠️  LINKEDOMICSCHAT_AWS_HOST not configured${NC}"
    read -p "Enter AWS host (e.g., ec2-user@1.2.3.4): " HOST_INPUT
    LINKEDOMICSCHAT_AWS_HOST="${HOST_INPUT:-$LINKEDOMICSCHAT_AWS_HOST}"
fi

# Expand ~ to $HOME in LOCAL paths only (bash doesn't expand ~ in variable assignments)
# Note: For REMOTE paths, ~ should be left as-is (SSH will expand it on remote side)
if [ ! -z "$LINKEDOMICSCHAT_AWS_KEY" ]; then
    # Expand ~ for local SSH key path
    LINKEDOMICSCHAT_AWS_KEY="${LINKEDOMICSCHAT_AWS_KEY/#\~/$HOME}"
fi
# Do NOT expand ~ in LINKEDOMICSCHAT_REMOTE_PATH - it's a remote path, SSH will expand it

# Check if SSH key exists
if [ ! -z "$LINKEDOMICSCHAT_AWS_KEY" ] && [ ! -f "$LINKEDOMICSCHAT_AWS_KEY" ]; then
    echo -e "${YELLOW}⚠️  SSH key not found at: $LINKEDOMICSCHAT_AWS_KEY${NC}"
    echo "   (Expanded path: ${LINKEDOMICSCHAT_AWS_KEY/#\~/$HOME})"
    read -p "Enter path to SSH key (or press Enter to use default SSH key): " KEY_INPUT
    if [ ! -z "$KEY_INPUT" ]; then
        LINKEDOMICSCHAT_AWS_KEY="${KEY_INPUT/#\~/$HOME}"  # Expand ~ in user input too
    else
        # Try to use default SSH key
        LINKEDOMICSCHAT_AWS_KEY=""
    fi
fi

# Build SSH command
SSH_CMD="ssh"
if [ ! -z "$LINKEDOMICSCHAT_AWS_KEY" ] && [ -f "$LINKEDOMICSCHAT_AWS_KEY" ]; then
    SSH_CMD="ssh -i $LINKEDOMICSCHAT_AWS_KEY"
fi

# Test SSH connection
echo "🔌 Testing SSH connection..."
if ! $SSH_CMD -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$LINKEDOMICSCHAT_AWS_HOST" "echo 'Connection successful'" > /dev/null 2>&1; then
    echo -e "${RED}❌ Cannot connect to $LINKEDOMICSCHAT_AWS_HOST${NC}"
    echo "Please check:"
    echo "  1. Instance is running"
    echo "  2. Security group allows SSH (port 22)"
    echo "  3. SSH key path is correct: $LINKEDOMICSCHAT_AWS_KEY"
    exit 1
fi
echo -e "${GREEN}✅ SSH connection successful${NC}"
echo ""

# Create rsync exclude file (respects .gitignore + adds server-specific files)
EXCLUDE_FILE=$(mktemp)
cat > "$EXCLUDE_FILE" << 'EOF'
# Git files
# .git/ excluded by default (saves space, not needed to run app)
# To include .git/ folder, set SYNC_GIT=true before running this script
EOF

# Conditionally exclude .git folder (can be overridden with LINKEDOMICSCHAT_SYNC_GIT=true)
if [[ "$LINKEDOMICSCHAT_SYNC_GIT" != "true" ]]; then
    echo ".git/" >> "$EXCLUDE_FILE"
    echo "# Note: .git/ excluded. Set LINKEDOMICSCHAT_SYNC_GIT=true to include it (enables 'git pull' on server)" >> "$EXCLUDE_FILE"
else
    echo "# .git/ folder will be synced (allows git pull on server)" >> "$EXCLUDE_FILE"
fi

cat >> "$EXCLUDE_FILE" << 'EOF'

# .gitignore and .gitattributes are kept (small, useful for documentation)

# Environment files (don't overwrite server .env)
.env
.env.local
.env.production

# Node modules (will be rebuilt in Docker)
node_modules/
.next/
out/

# Python cache
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
*.so
*.egg-info/

# IDE files
.vscode/
.idea/
*.swp
*.swo

# OS files
.DS_Store
Thumbs.db

# Logs
*.log
logs/

# Database files (server has its own)
*.db
*.sqlite
*.sqlite3
*.backup
*.bak

# Temporary files
tmp/
temp/
*.tmp

# Docker volumes (server-specific) — /data/ anchored to root so backend/data/ is still synced
/data/

# Virtual environments (should use Docker instead)
venv/
env/
ENV/
.venv/

# Build artifacts (rebuilt in Docker)
dist/
build/
*.egg-info/

# Coverage and test files
.coverage
.pytest_cache/
htmlcov/
.nyc_output/

# Backup files
*.backup
*.bak

# Personal/local-only folders
notes/

# Deployment scripts (optional - uncomment if you don't want to sync these)
# deploy_aws.sh
# deploy_rsync.sh
# deploy_config.sh

# SERVER-SPECIFIC FILES (protected from sync AND deletion)
# These patterns protect files that might exist on server but not in local repo
# Files matching these patterns will NEVER be synced or deleted
server-config.*
production-config.*
deploy-server-*.json
deploy-server-*.yaml
deploy-server-*.yml
server-data/
production-data/
deploy-logs/
server-backups/
deploy-custom-*.sh
server-init-*.sh
.env.production
.env.server
.env.deploy
server-monitoring/
custom-logs/
EOF

# Allow user to add custom server-specific files via environment variable
if [ ! -z "$LINKEDOMICSCHAT_SERVER_FILES" ]; then
    echo "" >> "$EXCLUDE_FILE"
    echo "# Custom server-specific files (from LINKEDOMICSCHAT_SERVER_FILES)" >> "$EXCLUDE_FILE"
    IFS=',' read -ra FILES <<< "$LINKEDOMICSCHAT_SERVER_FILES"
    for file in "${FILES[@]}"; do
        echo "$file" >> "$EXCLUDE_FILE"
    done
fi

echo "📦 Syncing files to server..."
echo "   From: $(pwd)"
echo "   To: $LINKEDOMICSCHAT_AWS_HOST:$LINKEDOMICSCHAT_REMOTE_PATH"
echo ""
echo -e "${YELLOW}ℹ️  Note: Remote path '~' will be expanded by SSH on the remote server${NC}"
echo ""

# Rsync command
# -a: archive mode (preserves permissions, timestamps, etc.)
# -v: verbose
# -z: compress during transfer
# --progress: show progress
# --exclude-from: use our exclude file
# NOTE: We do NOT use --delete flag, so files on server that don't exist locally will NOT be removed
# This is safer - server-specific files are preserved

# Check for dry-run mode
DRY_RUN="${LINKEDOMICSCHAT_DRY_RUN}"
RSYNC_OPTS="-avz --progress --exclude-from=$EXCLUDE_FILE"
if [[ "$DRY_RUN" == "true" ]]; then
    RSYNC_OPTS="$RSYNC_OPTS --dry-run"
    echo -e "${YELLOW}⚠️  DRY RUN MODE - No files will be changed${NC}"
    echo ""
fi

# Optional: Use --delete to remove files on server that don't exist locally
# WARNING: This will delete server-specific files! Use with caution.
USE_DELETE="${LINKEDOMICSCHAT_USE_DELETE}"
if [[ "$USE_DELETE" == "true" ]]; then
    RSYNC_OPTS="$RSYNC_OPTS --delete"
    echo -e "${RED}⚠️  WARNING: --delete enabled!${NC}"
    echo -e "${YELLOW}   Files on server that don't exist locally WILL BE DELETED${NC}"
    echo -e "${YELLOW}   Server-specific files are protected (see exclude list)${NC}"
    echo ""
    echo "Protected from deletion:"
    echo "  - .env, .env.production, .env.server"
    echo "  - *.db, *.sqlite (databases)"
    echo "  - server-config.*, production-config.*"
    echo "  - server-data/, production-data/"
    echo "  - Custom files (set LINKEDOMICSCHAT_SERVER_FILES to add more)"
    echo ""
    read -p "Continue with delete mode? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        rm -f "$EXCLUDE_FILE"
        exit 0
    fi
fi

# Perform sync
if [ ! -z "$LINKEDOMICSCHAT_AWS_KEY" ] && [ -f "$LINKEDOMICSCHAT_AWS_KEY" ]; then
    # Use SSH key
    rsync $RSYNC_OPTS \
        -e "ssh -i $LINKEDOMICSCHAT_AWS_KEY -o StrictHostKeyChecking=no" \
        --exclude='.git/' \
        --exclude='.env' \
        --exclude='node_modules/' \
        --exclude='.next/' \
        --exclude='__pycache__/' \
        --exclude='*.db' \
        --exclude='*.backup' \
        --exclude='*.bak' \
        ./ "$LINKEDOMICSCHAT_AWS_HOST:$LINKEDOMICSCHAT_REMOTE_PATH/"
else
    # Use default SSH
    rsync $RSYNC_OPTS \
        --exclude='.git/' \
        --exclude='.env' \
        --exclude='node_modules/' \
        --exclude='.next/' \
        --exclude='__pycache__/' \
        --exclude='*.db' \
        --exclude='*.backup' \
        --exclude='*.bak' \
        ./ "$LINKEDOMICSCHAT_AWS_HOST:$LINKEDOMICSCHAT_REMOTE_PATH/"
fi

# Clean up exclude file
rm -f "$EXCLUDE_FILE"

echo ""
echo -e "${GREEN}✅ Files synced successfully${NC}"
echo ""

# Ask if user wants to rebuild containers
read -p "Rebuild and restart Docker containers? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🔨 Rebuilding containers on server..."
    $SSH_CMD "$LINKEDOMICSCHAT_AWS_HOST" "cd $LINKEDOMICSCHAT_REMOTE_PATH && docker compose down && docker compose up -d --build"
    echo ""
    echo -e "${GREEN}✅ Deployment complete!${NC}"
    echo ""
    echo "📝 Next steps:"
    echo "   Check logs: ssh $LINKEDOMICSCHAT_AWS_HOST 'cd $LINKEDOMICSCHAT_REMOTE_PATH && docker compose logs -f'"
    echo "   View services: ssh $LINKEDOMICSCHAT_AWS_HOST 'cd $LINKEDOMICSCHAT_REMOTE_PATH && docker compose ps'"
else
    echo ""
    echo "ℹ️  Files synced. Containers not rebuilt."
    echo "   To rebuild manually:"
    echo "   ssh $LINKEDOMICSCHAT_AWS_HOST 'cd $LINKEDOMICSCHAT_REMOTE_PATH && docker compose up -d --build'"
fi

echo ""
