#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# MCP Governance Platform — Kurulum Script'i
# ──────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC} $1"; }

# ── Kontroller ──

info "Sistem gereksinimleri kontrol ediliyor..."

# Python
if ! command -v python3 &>/dev/null; then
    err "python3 bulunamadi. sudo apt install python3 python3-venv"
    exit 1
fi
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [ "$(echo "$PYVER >= 3.11" | bc -l 2>/dev/null || python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)')" ]; then
    info "Python $PYVER ✓"
else
    err "Python >= 3.11 gerekli (mevcut: $PYVER)"
    exit 1
fi

# uv
if ! command -v uv &>/dev/null; then
    warn "uv bulunamadi, yukleniyor..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi
info "uv $(uv --version) ✓"

# Ollama
if ! command -v ollama &>/dev/null; then
    warn "ollama bulunamadi. LLM planlama calismaz."
    warn "Kurulum: curl -fsSL https://ollama.com/install.sh | sh"
    warn "Model: ollama pull qwen3-coder:480b-cloud"
else
    info "ollama ✓"
fi

# ── Proje kurulumu ──

cd "$(dirname "$0")"

info "Python bagimliliklari yukleniyor..."
uv sync

if [ ! -f .env ]; then
    warn ".env dosyasi bulunamadi, .env.example kopyalaniyor..."
    cp .env.example .env
    echo -e "${YELLOW}>>> .env dosyasini duzenleyin: gerekli degiskenleri yazin${NC}"
fi

info ""
info "╔══════════════════════════════════════════════════╗"
info "║  Kurulum tamam!                                 ║"
info "╠══════════════════════════════════════════════════╣"
info "║  1. .env dosyasini duzenleyin                    ║"
info "║     .env dosyasina gerekli degiskenleri yazin      ║"
info "║                                                  ║"
info "║  2. Servisleri baslat:                           ║"
info "║     ./start.sh                                   ║"
info "║                                                  ║"
info "║  3. Dashboard: http://localhost:8080/dashboard    ║"
info "╚══════════════════════════════════════════════════╝"
