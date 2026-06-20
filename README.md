# MCP Governance Platform

Microsoft **Agent Governance Toolkit (AGT)** tabanlı merkezi MCP yönetişim platformu. Tüm MCP araçları ve agent'lar tek bir governance katmanından geçer.

## Mimari

```
Vibe
  │
  └── stdio ──► governance-gateway / gateway-mcp
                     │
                     ├── file-mcp   (8001)  dosya işlemleri
                     ├── shell-mcp  (8002)  shell komutları
                     ├── debian-mcp (8003/8004)  remote Debian SSH
                     │
                     ├── orchestrator-agent  (8013)  LLM planlama + delegasyon
                     ├── monitor-agent       (8014)  sistem izleme + LLM log analizi
                     ├── devops-agent        (8010)  DevOps operasyonları
                     ├── secops-agent        (8011)  güvenlik kontrolleri
                     └── sysadmin-agent      (8012)  sistem yönetimi
```

Gateway, MCP araçlarına proxy olurken, agent'lar hem doğrudan MCP çağrısı yapabilir hem de birbirleriyle konuşabilir. Orchestrator agent, kullanıcı task'larını LLM (Ollama) ile planlayıp diğer agent'lara dağıtır.

## LLM Kullanımı

Platformda LLM (Ollama, model: `qwen2.5:3b`) iki yerde kullanılır:

### 1. Orchestrator Agent (task planlama + özetleme)
- Kullanıcı task gelince registry'deki tüm agent'ları ve yeteneklerini dinamik okur
- Ollama'ya gönderir → LLM hangi agent/hangi tool'u çağıracağını `TOOL:` satırlarıyla planlar
- Orchestrator parse eder, her adımı gateway üzerinden ilgili agent'a iletir
- Tüm adımlar bitince sonuçlar tekrar Ollama'ya gönderilir → Türkçe özet üretilir

### 2. Monitor Agent (log analizi + restart kararı)
- Kritik servis DOWN algılanınca journalctl loglarını çeker
- Ollama'ya gönderir: "restart edilmeli mi?"
- LLM `YES` derse → restart; `NO` derse → skip; hata/ timeout → fallback restart

### LLM Kullanmayan Agent'lar
Devops, secops, sysadmin agent'ları saf tool executor'dır — hiç LLM çağırmaz, sadece gateway üzerinden MCP araçlarını çalıştırır.

## Agent'lar ve İletişim

| Agent | Port | LLM? | Görev | Diğer Agent'larla İletişim |
|-------|------|------|-------|---------------------------|
| **orchestrator** | 8013 | Evet (plan+özet) | Task planlama, delegasyon | LLM planıyla diğer tüm agent'ları çağırır |
| **monitor** | 8014 | Evet (log analizi) | Host/servis izleme, auto-fix | Bağımsız çalışır, diğer agent'larla konuşmaz |
| **devops** | 8010 | Hayır | Paket yönetimi, deploy | `ask_agent()` ile sysadmin-agent'a sorar |
| **secops** | 8011 | Hayır | Güvenlik taraması, UFW | `ask_agent()` ile sysadmin-agent'a sorar |
| **sysadmin** | 8012 | Hayır | Host komutları, servis yönetimi | Diğer agent'lardan gelen çağrıları yanıtlar |

İletişim mekanizmaları:
- **Orchestrator → diğer:** Gateway `/api/gateway/agent/{name}/ask` (governance atlanır)
- **devops/secops → sysadmin:** `_call_gateway()` ile governance üzerinden
- **Monitor:** Bağımsız, debian-mcp'ye doğrudan HTTP

## Monitor Agent (Oto-Fix)

Kritik servisler (`CRITICAL_SERVICES`: ssh, nginx, cron) periyodik olarak kontrol edilir:

1. Servis DOWN → journalctl loglarını al
2. **LLM analizi**: loglarda hata/config bozukluğu var mı?
3. `YES` → `service_restart` çağır; `NO` → atla (temiz durdurulmuş)
4. LLM yanıt vermezse (timeout) → güvenli tarafta kal, restart et

Ortam değişkenleri:
- `MONITOR_INTERVAL`: kontrol aralığı (sn, varsayılan 60)
- `MONITOR_AUTO_FIX`: true/false (varsayılan true)
- `CRITICAL_SERVICES`: virgülle ayrılmış servis listesi
- `OLLAMA_URL`: Ollama URL (varsayılan http://localhost:11434)
- `OLLAMA_MODEL`: Model adı (varsayılan qwen2.5:3b)
- `DEBIAN_MCP_URL`: debian-mcp adresi

## Servisler

| Servis | Port | Açıklama |
|--------|------|----------|
| **Governance Platform** | 8080 (HTTP) | FastAPI, REST API, policy engine, dashboard |
| **file-mcp** | 8001 (HTTP) | Dosya işlemleri |
| **shell-mcp** | 8002 (HTTP) | Shell komutları (allowlist) |
| **debian-mcp** | 8003/8004 (HTTP) | Remote Debian SSH yönetimi |
| **devops-agent** | 8010 (HTTP) | DevOps operasyonları |
| **secops-agent** | 8011 (HTTP) | Güvenlik kontrolleri |
| **sysadmin-agent** | 8012 (HTTP) | Sistem yönetimi |
| **orchestrator-agent** | 8013 (HTTP) | LLM task planlama + delegasyon |
| **monitor-agent** | 8014 (HTTP) | Host/servis izleme, auto-fix |
| **governance-gateway** | stdio (Vibe) | Policy enforcement MCP proxy |

## Host Yapılandırması

`config/hosts.yaml` dosyasında tanımlanır:

```yaml
hosts:
  hera:
    host: 161.35.134.181
    user: root
    port: 22
    description: "Debian 13 - DigitalOcean droplet"

  zeus:
    host: 159.203.109.102
    user: root
    port: 22
    description: "Debian server"
```

## Başlangıç

```bash
# Bağımlılıkları yükle
uv sync

# 1. MCP sunucularını başlat
uv run python mcp_servers/file_mcp.py &
uv run python mcp_servers/shell_mcp_http.py &
uv run uvicorn mcp_servers.debian_mcp:app --host 0.0.0.0 --port 8003 &

# 2. Agent'ları başlat
uv run python -m agents.devops_agent &
uv run python -m agents.secops_agent &
uv run python -m agents.sysadmin_agent &
uv run python -m agents.orchestrator &
uv run python -m agents.monitor_agent &

# 3. Governance platformunu başlat
uv run python main.py

# Tarayıcı: http://localhost:8080/dashboard
#      MCP Sunucuları: 8001-8003
#      Agent'lar:       8010-8014

# Vibe ile test (auto-approve ile)
alias vibe="vibe --auto-approve"
vibe
```

## API Referansı

### Governance Gateway

```bash
# Policy kontrolü
curl -X POST http://localhost:8080/api/gateway/govern \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"test","tool_name":"read_file","params":{"path":"/tmp/x"}}'

# file-mcp üzerinden dosya oku
curl -X POST http://localhost:8080/api/gateway/govern/file-mcp \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"test","tool_name":"read_file","params":{"path":"/home/user/file.txt"}}'

# Remote Debian host'ta komut çalıştır
curl -X POST http://localhost:8080/api/gateway/govern \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"test","tool_name":"ssh_exec","params":{"host_name":"hera","command":"uptime"}}'
```

### Registry

```bash
# MCP sunucularını listele
curl http://localhost:8080/api/registry/servers

# Yeni MCP sunucusu kaydet
curl -X POST http://localhost:8080/api/registry/servers \
  -H 'Content-Type: application/json' \
  -d '{"name":"custom-mcp","url":"http://192.168.1.100:9000","description":"...","capabilities":["tool1","tool2"]}'
```

### Remote Host Yönetimi

```bash
# Host'ları listele
curl -X POST http://127.0.0.1:8003/mcp -H 'Content-Type: application/json' \
  -d '{"method":"tools/call","params":{"name":"list_hosts","arguments":{}},"id":1}'

# Sistem bilgisi
curl -X POST http://127.0.0.1:8003/mcp -H 'Content-Type: application/json' \
  -d '{"method":"tools/call","params":{"name":"system_info","arguments":{"host_name":"hera"}},"id":1}'

# APT güncelleme
curl -X POST http://127.0.0.1:8003/mcp -H 'Content-Type: application/json' \
  -d '{"method":"tools/call","params":{"name":"deb_update","arguments":{"host_name":"hera"}},"id":1}'

# Servis durumu
curl -X POST http://127.0.0.1:8003/mcp -H 'Content-Type: application/json' \
  -d '{"method":"tools/call","params":{"name":"service_status","arguments":{"host_name":"hera","service":"ssh"}},"id":1}'

# Paket yükle
curl -X POST http://127.0.0.1:8003/mcp -H 'Content-Type: application/json' \
  -d '{"method":"tools/call","params":{"name":"deb_install","arguments":{"host_name":"hera","packages":"htop"}},"id":1}'

# Log görüntüle
curl -X POST http://127.0.0.1:8003/mcp -H 'Content-Type: application/json' \
  -d '{"method":"tools/call","params":{"name":"journalctl","arguments":{"host_name":"hera","service":"ssh","lines":20}},"id":1}'

# UFW durumu
curl -X POST http://127.0.0.1:8003/mcp -H 'Content-Type: application/json' \
  -d '{"method":"tools/call","params":{"name":"ufw_status","arguments":{"host_name":"hera"}},"id":1}'
```

## Policy Engine

Politikalar `policies/default-policy.yaml` dosyasında tanımlanır:

```yaml
rules:
  - name: allow-read-operations
    condition: tool_name in ["list_dir", "read_file", "search_files", "grep"]
    action: allow

  - name: write-requires-approval
    condition: tool_name == "write_file"
    action: require_approval
    message: "Write operation requires admin approval"

  - name: block-destructive-actions
    condition: params contains "init 0" or params contains "init 6" or params contains
      "sudo init" or params contains "rm -rf" or params contains "shutdown" or params
      contains "poweroff" or params contains "halt" or params contains "sudo poweroff"
      or params contains "sudo shutdown" or params contains "sudo halt" or params contains
      "sudo reboot" or params contains "||" or params contains "&&"
    message: Destructive action blocked by central policy
```

Dashboard üzerinden policy kuralları görüntülenebilir, eklenebilir ve düzenlenebilir.

## Docker ile debian-mcp

debian-mcp, Docker container'ında çalışır. SSH key'ler ve host config'i volume mount ile container'a aktarılır:

```yaml
# docker-compose.yml
services:
  debian-mcp:
    build:
      context: .
      dockerfile: mcp_servers/Dockerfile.debian-mcp
    ports:
      - "8003:8003"
    volumes:
      - ./config/hosts.yaml:/app/config/hosts.yaml:ro
      - ~/.ssh:/root/.ssh:ro
```

SSH private key asla image içine build edilmez, runtime'da `~/.ssh` volume mount edilir.

## Güvenlik Katmanı

İki katmanlı güvenlik:

### 1. Python Katmanı (`gateway.py` + `gateway_mcp.py`)

`ssh_exec` ve `run_shell` tool'ları için `command` parametresinde destructive pattern taraması:

- `init 0`, `init 6`, `shutdown`, `poweroff`, `halt`, `reboot`
- `rm -rf`, `mkfs`, `dd if=`, `fdisk`, ` parted`, `mkswap`
- `chmod 777 /`, `chown -R`, `> /dev/sd`, `:(){ :|:& };:`
- `wget -O /`, `curl -o /`, `mv /`, `cp /`
- `sudo` ile başlayan tüm komutlar engellenir
- `reboot_host` tool'u tamamen engellenmiştir

### 2. YAML Policy Katmanı (`policies/default-policy.yaml`)

Params string'inde `init 0`, `init 6`, `sudo shutdown`, `sudo poweroff`, `sudo halt`, `sudo reboot`, `rm -rf`, `||`, `&&` gibi pattern'ları tespit eder ve engeller.

## Vibe Entegrasyonu

`~/.vibe/config.toml` dosyasına eklendi:

```toml
[[mcp_servers]]
name = "governance-gateway"
transport = "stdio"
command = "uv"
args = ["--directory", "/home/murat/mcp-governance-platform", "run", "python", "mcp_servers/gateway_mcp.py"]
```

Vibe'a tek bir MCP sunucusu bağlanır, tüm araçlar governance katmanından geçer.

Vibe içinde kullanım:
```
# Local
system_info
uptime
disk_usage
process_list

# Remote (host_name ile)
uptime host_name="hera"
uptime host_name="zeus"
system_info host_name="hera"
deb_update host_name="hera"
service_status host_name="hera" service="ssh"
ssh_exec host_name="hera" command="uptime"
```

## Proje Yapısı

```
├── agents/
│   ├── base_agent.py             # BaseAgent sınıfı (MCP server, message polling, gateway çağrısı)
│   ├── devops_agent.py           # DevOps agent (port 8010)
│   ├── secops_agent.py           # Security agent (port 8011)
│   ├── sysadmin_agent.py         # Sistem yönetim agent'ı (port 8012)
│   ├── orchestrator.py           # Orchestrator agent — LLM planlama (port 8013)
│   └── monitor_agent.py          # Monitor agent — izleme + LLM log analizi (port 8014)
├── agt_gateway/
│   └── gateway.py                # AGT MCPGateway entegrasyonu (REST API)
├── config/
│   ├── settings.py               # Pydantic Settings
│   └── hosts.yaml                # Remote host tanımları
├── mcp_servers/
│   ├── Dockerfile.debian-mcp     # debian-mcp Docker imajı
│   ├── file_mcp.py               # file-mcp sunucusu (HTTP - FastAPI)
│   ├── shell_mcp.py              # shell-mcp (FastMCP)
│   ├── shell_mcp_http.py         # shell-mcp HTTP wrapper
│   ├── debian_mcp.py             # debian-mcp (HTTP - remote Debian yönetimi)
│   └── gateway_mcp.py            # Governance Gateway (stdio - Vibe için)
├── docker-compose.yml            # debian-mcp container orchestration
├── policies/
│   └── default-policy.yaml       # Varsayılan güvenlik politikası
├── registry/
│   └── api.py                    # MCP sunucu kaydı (CRUD)
├── templates/
│   └── index.html                # Dashboard (MCP + Agent ayrı sekmelerde)
├── main.py                       # Ana FastAPI uygulaması
├── pyproject.toml                # Proje yapılandırması (uv)
└── uv.lock                       # Kilitli bağımlılıklar
```

## Test Sonuçları

| Test | Sonuç |
|------|-------|
| Local file read/write | ✅ Allowed (policy + proxy) |
| Local shell | ✅ Allowed (policy + allowlist) |
| Remote SSH exec | ✅ Allowed (policy + proxy) |
| Remote system_info | ✅ Allowed (JSON response) |
| Remote APT update/install | ✅ Allowed |
| Remote service management | ✅ Allowed (systemctl) |
| Remote journalctl | ✅ Allowed |
| Remote UFW | ✅ Allowed |
| Dual-mode (local/remote) | ✅ system_info, uptime, disk_usage, process_list |
| PII Response Scan | ✅ Built-in sanitization |
| Vibe governance-gateway | ✅ 30+ araç kullanıma hazır |
| Dashboard | ✅ Policy rules, MCP/agent ayrı sekmeler, host durum kartları, Log Stream |
| Docker debian-mcp | ✅ Container'da SSH key mount ile çalışıyor |
| Destructive command blocking | ✅ `sudo init 0`, `sudo shutdown`, `reboot_host` engellendi |
| SSH sudo filter | ✅ Sudo ile başlayan tüm komutlar engellendi |
| Orchestrator LLM planlama | ✅ Task → LLM plan → agent delegasyon → özet |
| Monitor LLM log analizi | ✅ DOWN servis → journalctl → LLM kararı → restart/skip |
| Agent-agent iletişim | ✅ orchestrator→agent, devops/secops→sysadmin |
| Dashboard MCP/Agent ayrımı | ✅ MCP tab'ı sadece sunucular, Agent'lar tab'ı sadece agent'lar |
