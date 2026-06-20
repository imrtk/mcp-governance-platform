# MCP Governance Platform

Microsoft **Agent Governance Toolkit (AGT)** tabanlı merkezi MCP yönetişim platformu.
Tüm MCP araçları ve agent'lar tek bir governance katmanından geçer.

## Mimari

```
┌─ Kullanıcı ─────────────────────────────────────────────┐
│  Dashboard (8080)    Vibe CLI (stdio)    API (curl)      │
└──────────────────────────┬───────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │   Gateway   │  REST API :8080
                    │  main.py    │  Policy Engine
                    │  registry   │  Audit Log
                    └──────┬──────┘
                           │
          ┌────────────────┼──────────────────┐
          │                │                  │
   ┌──────▼──────┐  ┌─────▼──────┐   ┌──────▼──────┐
   │ Orchestrator│  │   Monitor  │   │ gateway_mcp │
   │ Agent :8013 │  │ Agent :8014│   │ (Vibe stdio)│
   │  LLM plan   │  │  60sn loop │   └──────┬──────┘
   │  + delegasyon│  │  tespit→   │          │
   └──────┬──────┘  │  orchestrat│   ┌──────┴──────┐
          │         └────────────┘   │ file-mcp:8001│
    ┌─────┼─────┐                    │ shell-mcp:8002│
    │     │     │                    │ debian-mcp:8003│
  ┌─▼─┐ ┌─▼─┐ ┌─▼──┐               │ do-mcp:8005   │
  │do │ │sys│ │dev │               └──────────────┘
  │agt│ │adm│ │ops │
  │15 │ │10 │ │11  │
  └───┘ └───┘ └────┘
```

## İşleyiş

1. **Monitor Agent** (8014) her 60sn'de host ve droplet'ları kontrol eder
2. Sorun tespit ederse **Orchestrator Agent**'a (8013) task gönderir
3. **Orchestrator** LLM (Ollama) ile plan yapar → hangi agent hangi tool'u çağıracak
4. **Gateway** üzerinden ilgili agent'a iletilir
5. Agent kendi MCP'sini çağırır (do-agent → do-mcp, sysadmin-agent → debian-mcp)
6. Tüm adımlar audit log, orchestrator history ve dashboard'da görünür

> **Hiçbir agent kendi başına hareket etmez.** Sadece orchestrator çağırdığında çalışır.
> Monitor sadece tespit eder, direkt fix yapmaz — orchestrator'a task gönderir.

## Ortam Değişkenleri

```bash
# Zorunlu
DO_API_TOKEN="dop_v1_..."       # DigitalOcean API token (project scope)
DO_PROJECT_ID="..."              # HBDMS proje ID'si

# Opsiyonel
GATEWAY_URL="http://localhost:8080"
OLLAMA_URL="http://localhost:11434"
OLLAMA_MODEL="qwen3-coder:480b-cloud"
MONITOR_INTERVAL="60"
MONITOR_AUTO_FIX="true"
```

## Gereksinimler

| Bağımlılık | Versiyon | Açıklama |
|---|---|---|
| Python | >= 3.11 | Runtime |
| Ollama | latest | LLM için (orchestrator planlama) |
| uv | latest | Python paket yöneticisi |
| Docker | latest | debian-mcp container'ı için |
| SSH keys | - | Remote host erişimi için |

## Hızlı Başlangıç

```bash
# 1. Repo'yu clone'la
git clone <repo-url>
cd mcp-governance-platform

# 2. .env dosyasını oluştur
cp .env.example .env
# .env dosyasını düzenle: DO_API_TOKEN, DO_PROJECT_ID, host IP'leri

# 3. Bağımlılıkları yükle
uv sync

# 4. debian-mcp Docker container'ını başlat
docker compose up -d

# 5. Tüm servisleri başlat
chmod +x start.sh
./start.sh

# 6. Dashboard
open http://localhost:8080/dashboard
```

## Servisler

| Servis | Port | Tür | Açıklama |
|---|---|---|---|
| **main (gateway)** | 8080 | REST API | Governance, registry, dashboard, audit |
| **file-mcp** | 8001 | HTTP MCP | Dosya işlemleri |
| **shell-mcp** | 8002 | HTTP MCP | Shell komutları (allowlist) |
| **debian-mcp** | 8003 | HTTP MCP | Remote Debian SSH yönetimi (Docker) |
| **do-mcp** | 8005 | HTTP MCP | DigitalOcean droplet yönetimi |
| **orchestrator-agent** | 8013 | HTTP MCP | LLM planlama + delegasyon |
| **monitor-agent** | 8014 | HTTP MCP | Host/servis/droplet izleme |
| **sysadmin-agent** | 8010 | HTTP MCP | Sistem yönetimi |
| **devops-agent** | 8011 | HTTP MCP | DevOps operasyonları |
| **secops-agent** | 8012 | HTTP MCP | Güvenlik kontrolleri |
| **do-agent** | 8015 | HTTP MCP | DO droplet yönetimi |
| **Ollama** | 11434 | HTTP | LLM servisi |

## Agent'lar ve İletişim

| Agent | Port | LLM? | Görev | Kim Çağırır |
|---|---|---|---|---|
| **orchestrator** | 8013 | Evet (plan+özet) | Task planlama, delegasyon | Monitor, kullanıcı (dashboard/Vibe/API) |
| **monitor** | 8014 | Hayır | Host/servis/droplet izleme | Bağımsız loop (60sn) — tespit edince orchestrator'a bildirir |
| **do-agent** | 8015 | Hayır | DO droplet power on/off/status | Orchestrator |
| **sysadmin** | 8010 | Hayır | Host komutları, servis yönetimi | Orchestrator |
| **devops** | 8011 | Hayır | Paket yönetimi, deploy | Orchestrator |
| **secops** | 8012 | Hayır | Güvenlik taraması, UFW | Orchestrator |

Tüm iletişim **gateway** üzerinden geçer → policy enforcement, audit log, agent message log.

## Dashboard

`http://localhost:8080/dashboard`

Sekmeler:
- **Policy Rules** — Governance kuralları (ekle/sil/düzenle)
- **YAML Editor** — Policy YAML düzenleme
- **MCP Servers** — Kayıtlı MCP sunucuları
- **Agent'lar** — Agent durumları, tool listeleri
- **Orchestrator** — LLM execution history (plan, adımlar, sonuçlar)
- **Audit Log** — Policy kararları (allow/block)
- **Agent Konuşmaları** — Agent'lar arası iletişim
- **Log Akışı** — Tüm olaylar canlı akış

Dashboard 1.5sn'de bir otomatik güncellenir.

## API Kullanımı

```bash
# Orchestrator'a task gönder
curl -X POST http://localhost:8080/api/gateway/agent/orchestrator-agent/ask \
  -H 'Content-Type: application/json' \
  -d '{"tool_name":"ask","params":{"task":"zeus dropleti kontrol et"}}'

# Monitor durumu
curl http://localhost:8080/api/gateway/monitor/status

# Orchestrator history
curl http://localhost:8080/api/gateway/orchestrator/history

# Audit log
curl http://localhost:8080/api/gateway/audit?limit=50

# Agent iletişim log'u
curl http://localhost:8080/api/gateway/agent/log?limit=50

# Registry'deki tüm servisler
curl http://localhost:8080/api/registry/servers
```

## Policy Engine

`policies/default-policy.yaml` ile tanımlanır. Dashboard üzerinden düzenlenebilir.

İki katmanlı güvenlik:
1. **Python katmanı** — `ssh_exec`/`run_shell`'de destructive komut taraması
2. **YAML policy katmanı** — parametre bazlı engelleme

## Proje Yapısı

```
├── agents/                    # Agent'lar (MCP server)
│   ├── base_agent.py          # BaseAgent sınıfı
│   ├── orchestrator.py        # LLM planlama + delegasyon
│   ├── monitor_agent.py       # Periyodik izleme
│   ├── do_agent.py            # DO droplet yönetimi
│   ├── sysadmin_agent.py      # Sistem yönetimi
│   ├── devops_agent.py        # DevOps operasyonları
│   └── secops_agent.py        # Güvenlik kontrolleri
├── agt_gateway/
│   └── gateway.py             # REST API gateway + policy engine
├── mcp_servers/               # MCP sunucuları (backend)
│   ├── file_mcp.py
│   ├── shell_mcp.py
│   ├── shell_mcp_http.py
│   ├── debian_mcp.py
│   ├── do_mcp.py
│   ├── gateway_mcp.py         # Vibe MCP proxy
│   └── Dockerfile.debian-mcp
├── registry/
│   └── api.py                 # Servis kaydı
├── templates/
│   └── index.html             # Dashboard
├── config/
│   ├── hosts.yaml             # SSH host tanımları
│   └── settings.py
├── policies/
│   └── default-policy.yaml
├── main.py                    # FastAPI uygulaması
├── setup.sh                   # Kurulum script'i
├── start.sh                   # Servis başlatma script'i
├── docker-compose.yml         # debian-mcp container
├── .env.example               # Örnek env dosyası
├── pyproject.toml
└── uv.lock
```
