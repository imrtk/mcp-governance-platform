#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# MCP Governance Platform — Servis Başlatma
# ──────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC} $1"; }

cd "$(dirname "$0")"

# .env kontrol
if [ ! -f .env ]; then
    err ".env dosyasi bulunamadi! cp .env.example .env && duzenleyin"
    exit 1
fi

# Container (debian-mcp)
if command -v docker &>/dev/null; then
    if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q debian-mcp; then
        info "debian-mcp container'i baslatiliyor..."
        docker compose up -d 2>/dev/null || warn "Docker baslatilamadi"
    else
        info "debian-mcp container'i zaten calisiyor"
    fi
else
    warn "docker bulunamadi, debian-mcp atlaniyor"
fi

# ── PID dosyalarini temizle ──
cleanup() {
    info "Servisler durduruluyor..."
    pkill -f "uvicorn.*mcp_servers\." 2>/dev/null || true
    pkill -f "agents\." 2>/dev/null || true
    pkill -f "main.py" 2>/dev/null || true
    sleep 1
}
trap cleanup EXIT

# ── MCP sunuculari ──
info "MCP sunuculari baslatiliyor..."

uv run python mcp_servers/file_mcp.py &
sleep 1

uv run python mcp_servers/shell_mcp_http.py &
sleep 1

uv run uvicorn mcp_servers.debian_mcp:app --host 0.0.0.0 --port 8003 &
sleep 1

uv run uvicorn mcp_servers.do_mcp:app --host 0.0.0.0 --port 8005 &
sleep 1

# ── Agent'lar ──
info "Agent'lar baslatiliyor..."

uv run python -m agents.sysadmin_agent &
sleep 1

uv run python -m agents.devops_agent &
sleep 1

uv run python -m agents.secops_agent &
sleep 1

uv run python -m agents.orchestrator &
sleep 1

uv run python -m agents.monitor_agent &
sleep 1

uv run python -m agents.do_agent &
sleep 1

# ── Governance platformu ──
info "Governance platformu baslatiliyor (8080)..."
uv run python main.py
