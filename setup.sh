#!/usr/bin/env bash
# Wayfarer — One-command setup
# Usage: curl -sSL https://raw.githubusercontent.com/anubhavsanket/wayfarer/main/setup.sh | bash
# Or clone the repo and run: bash setup.sh
#
# This script:
# 1. Clones the repo (if not already cloned)
# 2. Copies .env.example → .env (won't overwrite existing .env)
# 3. Pulls Docker images + embedding model
# 4. Starts the full stack

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Wayfarer — AI Job Search Platform   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""

# Check prerequisites
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed.${NC}"
    echo "Install Docker from https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo -e "${RED}Error: Docker Compose is not installed.${NC}"
    echo "Install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

# Check if we're already in the wayfarer directory
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${YELLOW}Cloning Wayfarer...${NC}"
    git clone https://github.com/anubhavsanket/wayfarer.git wayfarer
    cd wayfarer
fi

# Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Creating .env from template...${NC}"
    cp .env.example .env
    echo -e "${GREEN}Created .env — edit it to add your API keys.${NC}"
    echo ""
    echo "Required keys (at least one LLM provider):"
    echo "  NVIDIA_NIM_API_KEY  (free at build.nvidia.com)"
    echo "  OPENROUTER_API_KEY  (free at openrouter.ai)"
    echo ""
    echo "For search (Stage 1):"
    echo "  TAVILY_API_KEY      (free at tavily.com)"
    echo ""
    echo "For job boards (Stage 3):"
    echo "  BLUEDOOR_API_KEY    (free at bluedoor.sh/apis/job-postings)"
    echo ""
    echo "Or set LLM_PROVIDER=ollama in .env for fully local inference (no API keys needed)."
    echo ""
fi

# Build and start
echo -e "${GREEN}Building and starting Wayfarer...${NC}"
docker compose up --build -d

echo ""
echo -e "${GREEN}Waiting for services to start...${NC}"
sleep 30

# Pull embedding model
echo -e "${YELLOW}Pulling embedding model (first time only)...${NC}"
docker compose exec ollama ollama pull nomic-embed-text 2>/dev/null || true

# Pull chat model (for Ollama mode)
if grep -q "LLM_PROVIDER=ollama" .env; then
    echo -e "${YELLOW}Pulling chat model for local inference...${NC}"
    docker compose exec ollama ollama pull llama3.2:3b 2>/dev/null || true
fi

# Health check
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  Wayfarer is ready!${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo "  Frontend:     http://localhost:3000"
echo "  API docs:     http://localhost:8000/docs"
echo "  Health check: http://localhost:8000/health"
echo ""
echo "  First time? Open the Settings tab in the frontend to enter your API keys,"
echo "  or edit the .env file and restart with: docker compose up -d"
echo ""
