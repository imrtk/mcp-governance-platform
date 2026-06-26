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
           ┌────────────────┼──────────────────┬─────────────────┐
           │                │                  │                 │
    ┌──────▼──────┐  ┌─────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
    │ Orchestrator│  │   Monitor  │   │ vcenter-mcp │   │   zabbix    │
    │ Agent :8013 │  │ Agent :8014│   │    :8006    │   │  MCP :8030  │
    │  LLM plan   │  │  60sn loop │   │ vcenter-agt │   │  zabbix-agt │
    │  + delegasyon│  │  tespit→   │   │    :8016    │   │  :8031      │
    └──────┬──────┘  │  orchestrat│   └──────┬──────┘   └──────┬──────┘
           │         └────────────┘          │                 │
     ┌─────┼─────┐                    ┌──────┴──────┐   ┌──────┴──────┐
     │           │                    │  pgsql-mcp  │   │  Postgres   │
     │   vcenter │                    │    :8020    │   │   DB        │
     │   agent   │                    │  pgsql-agt  │   │  192.168..  │
     │   :8016   │                    │    :8021    │   └─────────────┘
     └───────────┘                    └─────────────┘
```

## İşleyiş

1. **Monitor Agent** (8014) her 60sn'de vCenter VM'leri + Zabbix alert'lerini kontrol eder
2. Sorun tespit ederse **Orchestrator Agent**'a (8013) task gönderir
3. **Orchestrator** LLM ile plan yapar → hangi agent hangi tool'u çağıracak
4. **Gateway** üzerinden ilgili agent'a iletilir
5. Agent kendi MCP'sini çağırır (vcenter-agent → vcenter-mcp, pgsql-agent → pgsql-mcp)
6. Tüm adımlar audit log, orchestrator history ve dashboard'da görünür

> **Hiçbir agent kendi başına hareket etmez.** Sadece orchestrator çağırdığında çalışır.
> Monitor sadece tespit eder, direkt fix yapmaz — orchestrator'a task gönderir.

## Ortam Değişkenleri

```bash
# LLM API (OpenAI-compatible)
LLM_API_URL="http://localhost:11434/v1/chat/completions"
LLM_API_KEY=""
LLM_MODEL="qwen3-coder:480b-cloud"

# Monitor
MONITOR_INTERVAL="60"
MONITOR_AUTO_FIX="true"

# Gateway
GATEWAY_URL="http://localhost:8080"
```

## Gereksinimler

| Bağımlılık | Versiyon | Açıklama |
|---|---|---|
| Python | >= 3.11 | Runtime |
| uv | latest | Python paket yöneticisi |

## Hızlı Başlangıç

```bash
# 1. Repo'yu clone'la
git clone <repo-url>
cd mcp-governance-platform

# 2. .env dosyasını oluştur
cp .env.example .env
# .env dosyasını düzenle: gerekli değişkenleri gir

# 3. Bağımlılıkları yükle
uv sync

# 4. Tüm servisleri başlat
chmod +x start.sh
./start.sh

# 5. Dashboard
open http://localhost:8080/dashboard
```

## Servisler

| Servis | Port | Tür | Açıklama |
|---|---|---|---|
| **main (gateway)** | 8080 | REST API | Governance, registry, dashboard, audit |
| **vcenter-mcp** | 8006 | HTTP MCP | vCenter VM yönetimi |
| **pgsql-mcp** | 8020 | HTTP MCP | PostgreSQL veritabanı işlemleri |
| **zabbix-mcp** | 8030 | HTTP MCP | Zabbix monitoring entegrasyonu |
| **orchestrator-agent** | 8013 | HTTP MCP | LLM planlama + delegasyon |
| **monitor-agent** | 8014 | HTTP MCP | vCenter/Zabbix izleme |
| **vcenter-agent** | 8016 | HTTP MCP | vCenter VM yönetimi |
| **pgsql-agent** | 8021 | HTTP MCP | PostgreSQL sorgu + alert logging |
| **zabbix-agent** | 8031 | HTTP MCP | Zabbix host/alert/metric yönetimi |

## Agent'lar ve İletişim

| Agent | Port | LLM? | Görev | Kim Çağırır |
|---|---|---|---|---|
| **orchestrator** | 8013 | Evet (plan+özet) | Task planlama, delegasyon | Monitor, kullanıcı (dashboard/Vibe/API) |
| **monitor** | 8014 | Hayır | vCenter VM/kaynak/event + Zabbix alert izleme | Bağımsız loop (60sn) — tespit edince orchestrator'a bildirir |
| **vcenter-agent** | 8016 | Hayır | vCenter VM yönetimi (power, deploy, snapshot) | Orchestrator |
| **pgsql-agent** | 8021 | Hayır | PostgreSQL sorgu, alert logging, metric | Orchestrator |
| **zabbix-agent** | 8031 | Hayır | Zabbix host/alert/metric/event yönetimi | Orchestrator |

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
  -d '{"tool_name":"ask","params":{"task":"hera host durumunu kontrol et"}}'

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

**YAML policy katmanı** ile parametre bazlı engelleme yapılır.

## Proje Yapısı

```
├── agents/                    # Agent'lar (MCP server)
│   ├── base_agent.py          # BaseAgent sınıfı
│   ├── orchestrator.py        # LLM planlama + delegasyon
│   ├── monitor_agent.py       # Periyodik izleme
│   ├── vcenter_agent.py       # vCenter VM yönetimi
│   ├── pgsql_agent.py         # PostgreSQL agent
│   └── zabbix_agent.py        # Zabbix monitoring agent
├── agt_gateway/
│   └── gateway.py             # REST API gateway + policy engine
├── mcp_servers/               # MCP sunucuları (backend)
│   ├── vcenter_mcp.py
│   ├── pgsql_mcp.py
│   ├── zabbix_mcp.py
│   └── gateway_mcp.py         # Vibe MCP proxy
├── registry/
│   └── api.py                 # Servis kaydı
├── templates/
│   └── index.html             # Dashboard
├── config/
│   └── settings.py
├── policies/
│   └── default-policy.yaml
├── main.py                    # FastAPI uygulaması
├── setup.sh                   # Kurulum script'i
├── start.sh                   # Servis başlatma script'i
├── .env.example               # Örnek env dosyası
├── pyproject.toml
└── uv.lock
```
