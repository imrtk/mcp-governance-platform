#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# MCP Governance Platform — Servis Başlatma (vCenter only)
# ──────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC} $1"; }

cd "$(dirname "$0")"

if [ ! -f .env ]; then
    err ".env dosyasi bulunamadi! cp .env.example .env && duzenleyin"
    exit 1
fi

cleanup() {
    info "Servisler durduruluyor..."
    pkill -f "uvicorn.*vcenter_mcp" 2>/dev/null || true
    pkill -f "agents\." 2>/dev/null || true
    pkill -f "main.py" 2>/dev/null || true
    sleep 1
}
trap cleanup EXIT

# ── MCP sunuculari ──
info "vcenter-mcp baslatiliyor (8006)..."
uv run uvicorn mcp_servers.vcenter_mcp:app --host 0.0.0.0 --port 8006 &
sleep 1

# ── Agent'lar ──
info "orchestrator-agent baslatiliyor (8013)..."
uv run python -m agents.orchestrator &
sleep 1

info "vcenter-agent baslatiliyor (8016)..."
uv run python -m agents.vcenter_agent &
sleep 1

info "monitor-agent baslatiliyor (8014)..."
uv run python -m agents.monitor_agent &
sleep 1

info "pgsql-mcp baslatiliyor (8020)..."
uv run uvicorn mcp_servers.pgsql_mcp:app --host 0.0.0.0 --port 8020 &
sleep 1

info "pgsql-agent baslatiliyor (8021)..."
uv run python -m agents.pgsql_agent &
sleep 1

# ── Governance platformu ──
info "Governance platformu baslatiliyor (8080)..."
uv run python main.py
