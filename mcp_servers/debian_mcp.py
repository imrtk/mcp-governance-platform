import subprocess, json, os, yaml
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel

CONFIG_PATH = Path(__file__).parent.parent / "config" / "hosts.yaml"

def _load_hosts() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            data = yaml.safe_load(f)
        return data.get("hosts", {})
    return {}

HOSTS = _load_hosts()

def _resolve(args: dict) -> tuple:
    host_name = args.get("host_name", "")
    if host_name:
        entry = HOSTS.get(host_name)
        if not entry:
            raise ValueError(f"Unknown host: {host_name}. Use 'list_hosts' to see available hosts.")
        return entry["host"], entry.get("user", ""), entry.get("port", 22)
    return args.get("host", ""), args.get("user", ""), args.get("port", 22)

TOOLS = [
    {
        "name": "list_hosts",
        "description": "List configured remote Debian hosts",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "ssh_exec",
        "description": "Run any command on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address (if not using host_name)"},
                "command": {"type": "string", "description": "Command to run"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            },
            "required": ["command"]
        }
    },
    {
        "name": "system_info",
        "description": "Get OS, CPU, memory, disk info from a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    },
    {
        "name": "uptime",
        "description": "Get system uptime from a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    },
    {
        "name": "deb_update",
        "description": "Run apt update on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            },
            "required": []
        }
    },
    {
        "name": "deb_upgrade",
        "description": "Run apt upgrade -y on a remote Debian host (installs available updates)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            },
            "required": []
        }
    },
    {
        "name": "deb_install",
        "description": "Install packages via apt on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "packages": {"type": "string", "description": "Package(s) to install (space-separated)"}
            },
            "required": ["packages"]
        }
    },
    {
        "name": "deb_remove",
        "description": "Remove packages via apt on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "packages": {"type": "string", "description": "Package(s) to remove (space-separated)"}
            },
            "required": ["packages"]
        }
    },
    {
        "name": "deb_search",
        "description": "Search for packages via apt-cache on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "query": {"type": "string", "description": "Package search query"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "deb_list_upgradable",
        "description": "List upgradable packages on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    },
    {
        "name": "deb_autoremove",
        "description": "Run apt autoremove to clean unused packages",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    },
    {
        "name": "service_status",
        "description": "Check status of a systemd service on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "service": {"type": "string", "description": "Service name (e.g. nginx, ssh)"}
            },
            "required": ["service"]
        }
    },
    {
        "name": "service_restart",
        "description": "Restart a systemd service on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "service": {"type": "string", "description": "Service name (e.g. nginx, ssh)"}
            },
            "required": ["service"]
        }
    },
    {
        "name": "service_start",
        "description": "Start a systemd service on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "service": {"type": "string", "description": "Service name"}
            },
            "required": ["service"]
        }
    },
    {
        "name": "service_stop",
        "description": "Stop a systemd service on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "service": {"type": "string", "description": "Service name"}
            },
            "required": ["service"]
        }
    },
    {
        "name": "service_enable",
        "description": "Enable a systemd service on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "service": {"type": "string", "description": "Service name"}
            },
            "required": ["service"]
        }
    },
    {
        "name": "journalctl",
        "description": "View system logs via journalctl on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "service": {"type": "string", "description": "Filter by service (optional)", "default": ""},
                "lines": {"type": "integer", "description": "Number of lines", "default": 50}
            }
        }
    },
    {
        "name": "ufw_status",
        "description": "Check UFW firewall status on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    },
    {
        "name": "ufw_allow",
        "description": "Allow a port/service in UFW on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "rule": {"type": "string", "description": "Port or service (e.g. 80/tcp, OpenSSH)"}
            },
            "required": ["rule"]
        }
    },
    {
        "name": "disk_usage",
        "description": "Show disk usage on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    },
    {
        "name": "process_list",
        "description": "List top processes by CPU/memory on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "sort": {"type": "string", "description": "Sort by: cpu or memory", "default": "cpu"},
                "count": {"type": "integer", "description": "Number of processes", "default": 10}
            }
        }
    },
    {
        "name": "reboot_host",
        "description": "Reboot a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    },
    {
        "name": "network",
        "description": "Network diagnostics on a remote Debian host (ping, ports, connections, dns, curl, traceroute)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "action": {"type": "string", "description": "ping, ports, connections, dns, curl, traceroute", "default": "ping"},
                "target": {"type": "string", "description": "Target IP/hostname/URL (for ping, dns, curl, traceroute)", "default": ""}
            },
            "required": ["action"]
        }
    },
    {
        "name": "cpu_usage",
        "description": "Show CPU usage metrics (load avg, per-core usage) on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    },
    {
        "name": "memory_info",
        "description": "Show detailed memory usage on a remote Debian host (total, used, free, swap)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    },
    {
        "name": "disk_info",
        "description": "Show disk usage per mount point and inode usage on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    },
    {
        "name": "network_traffic",
        "description": "Show network interface traffic stats (rx/tx bytes, packets, errors) on a remote Debian host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    },
    {
        "name": "io_stats",
        "description": "Show disk I/O stats on a remote Debian host (tps, read/write speed)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
                "port": {"type": "integer", "description": "SSH port", "default": 22}
            }
        }
    }
]

def _list_hosts(args: dict) -> str:
    if not HOSTS:
        return "No hosts configured"
    lines = []
    for name, info in HOSTS.items():
        desc = info.get("description", "")
        lines.append(f"  {name}: {info['host']} ({info.get('user','root')}){ ' - ' + desc if desc else ''}")
    return "Configured hosts:\n" + "\n".join(lines)

def _ssh(host: str, command: str, user: str = "", port: int = 22) -> str:
    ssh_cmd = ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no"]
    if port != 22:
        ssh_cmd.extend(["-p", str(port)])
    target = f"{user}@{host}" if user else host
    ssh_cmd.append(target)
    ssh_cmd.append(command)
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=20)
        if result.returncode == 0:
            return result.stdout.strip()
        err = result.stderr.strip()
        return f"[EXIT {result.returncode}] {err}" if err else f"[EXIT {result.returncode}]"
    except subprocess.TimeoutExpired:
        return "[SSH ERROR] Connection timed out"
    except FileNotFoundError:
        return "[SSH ERROR] SSH client not found"
    except Exception as e:
        return f"[SSH ERROR] {e}"

def _run(args: dict, cmd: str) -> str:
    host, user, port = _resolve(args)
    return _ssh(host, cmd, user, port)

def _network(args: dict) -> str:
    action = args.get("action", "ping")
    target = args.get("target", "")
    host, user, port = _resolve(args)
    if action == "ping":
        t = target or "8.8.8.8"
        return _ssh(host, f"ping -c 4 {t} 2>&1", user, port)
    elif action == "ports":
        return _ssh(host, "ss -tlnp 2>&1 || netstat -tlnp 2>&1", user, port)
    elif action == "connections":
        return _ssh(host, "ss -tupn 2>&1 || netstat -tupn 2>&1", user, port)
    elif action == "dns":
        t = target or "google.com"
        return _ssh(host, f"dig {t} 2>&1 || nslookup {t} 2>&1", user, port)
    elif action == "curl":
        t = target or "https://example.com"
        return _ssh(host, f"curl -sI --max-time 10 {t} 2>&1 || echo 'curl failed'", user, port)
    elif action == "traceroute":
        t = target or "8.8.8.8"
        return _ssh(host, f"traceroute -n {t} 2>&1 || echo 'traceroute not installed'", user, port)
    return f"Unknown action: {action}. Use: ping, ports, connections, dns, curl, traceroute"

def _cpu_usage(args: dict) -> str:
    host, user, port = _resolve(args)
    lines = []
    lines.append("=== Load Average ===")
    lines.append(_ssh(host, "cat /proc/loadavg", user, port))
    lines.append("")
    lines.append("=== Per-Core Usage ===")
    lines.append(_ssh(host, "mpstat -P ALL 2>&1 || (cat /proc/stat | head -$(($(nproc)+1)))", user, port))
    lines.append("")
    lines.append("=== Top CPU Processes ===")
    lines.append(_ssh(host, "ps aux --sort=-%cpu | head -6", user, port))
    return "\n".join(lines)

def _memory_info(args: dict) -> str:
    host, user, port = _resolve(args)
    lines = []
    lines.append("=== Memory (free -h) ===")
    lines.append(_ssh(host, "free -h", user, port))
    lines.append("")
    lines.append("=== Top Memory Processes ===")
    lines.append(_ssh(host, "ps aux --sort=-%mem | head -6", user, port))
    return "\n".join(lines)

def _disk_info(args: dict) -> str:
    host, user, port = _resolve(args)
    lines = []
    lines.append("=== Disk Usage (df -h) ===")
    lines.append(_ssh(host, "df -h 2>&1", user, port))
    lines.append("")
    lines.append("=== Inode Usage (df -i) ===")
    lines.append(_ssh(host, "df -i 2>&1", user, port))
    return "\n".join(lines)

def _network_traffic(args: dict) -> str:
    host, user, port = _resolve(args)
    lines = []
    lines.append("=== Network Interfaces ===")
    lines.append(_ssh(host, "ip -s link 2>&1 || cat /proc/net/dev", user, port))
    lines.append("")
    lines.append("=== Routing Table ===")
    lines.append(_ssh(host, "ip route 2>&1 || route -n 2>&1", user, port))
    return "\n".join(lines)

def _io_stats(args: dict) -> str:
    host, user, port = _resolve(args)
    lines = []
    lines.append("=== Disk I/O (iostat -x) ===")
    lines.append(_ssh(host, "iostat -x 2>&1 || (cat /proc/diskstats | head -20)", user, port))
    lines.append("")
    lines.append("=== Mount Points ===")
    lines.append(_ssh(host, "mount | grep '^/dev'", user, port))
    return "\n".join(lines)

def _system_info(host: str, user: str = "", port: int = 22) -> str:
    hostname = _ssh(host, "hostname", user, port)
    os_info = _ssh(host, "cat /etc/os-release | grep -E '^PRETTY_NAME' | cut -d= -f2 | tr -d '\"'", user, port)
    release = _ssh(host, "uname -r", user, port)
    cpu = _ssh(host, "nproc", user, port)
    uptime_str = _ssh(host, "uptime -p", user, port)
    memory = _ssh(host, "free -h | grep ^Mem: | tr -s ' ' | cut -d' ' -f3,2 | tr ' ' '/'", user, port)
    disk = _ssh(host, "df -h / | tail -1 | tr -s ' ' | cut -d' ' -f3,4 | tr ' ' '/'", user, port)
    load = _ssh(host, "uptime | awk -F'load average:' '{print $2}' | xargs", user, port)
    info = {"hostname": hostname, "os": os_info, "kernel": release,
            "cpu_cores": cpu, "uptime": uptime_str, "memory_used/total": memory,
            "disk_used/total": disk, "load_avg": load}
    return json.dumps(info, indent=2)

TOOL_FUNCS = {
    "list_hosts": lambda a: _list_hosts(a),
    "ssh_exec": lambda a: _run(a, a.get("command", "")),
    "system_info": lambda a: _system_info(*_resolve(a)),
    "uptime": lambda a: _run(a, "uptime"),
    "deb_update": lambda a: _run(a, "apt update 2>&1"),
    "deb_upgrade": lambda a: _run(a, "apt upgrade -y 2>&1"),
    "deb_install": lambda a: _run(a, f"apt install -y {a.get('packages','')} 2>&1"),
    "deb_remove": lambda a: _run(a, f"apt remove -y {a.get('packages','')} 2>&1"),
    "deb_search": lambda a: _run(a, f"apt-cache search '{a.get('query','')}' 2>&1"),
    "deb_list_upgradable": lambda a: _run(a, "apt list --upgradable 2>/dev/null"),
    "deb_autoremove": lambda a: _run(a, "apt autoremove -y 2>&1"),
    "service_status": lambda a: _run(a, f"systemctl status {a.get('service','')} --no-pager 2>&1"),
    "service_restart": lambda a: _run(a, f"systemctl restart {a.get('service','')} 2>&1 && echo 'OK: {a.get('service','')} restarted'"),
    "service_start": lambda a: _run(a, f"systemctl start {a.get('service','')} 2>&1 && echo 'OK: {a.get('service','')} started'"),
    "service_stop": lambda a: _run(a, f"systemctl stop {a.get('service','')} 2>&1 && echo 'OK: {a.get('service','')} stopped'"),
    "service_enable": lambda a: _run(a, f"systemctl enable {a.get('service','')} 2>&1 && echo 'OK: {a.get('service','')} enabled'"),
    "journalctl": lambda a: _run(a, f"journalctl {'-u ' + a.get('service','') if a.get('service') else ''} -n {a.get('lines',50)} --no-pager 2>&1"),
    "ufw_status": lambda a: _run(a, "ufw status verbose 2>&1"),
    "ufw_allow": lambda a: _run(a, f"ufw allow {a.get('rule','')} 2>&1"),
    "disk_usage": lambda a: _run(a, "df -h 2>&1"),
    "process_list": lambda a: _run(a, f"ps aux --sort=-%{a.get('sort','cpu')[0].upper()} | head -{a.get('count',10) + 1}"),
    "network": lambda a: _network(a),
    "cpu_usage": lambda a: _cpu_usage(a),
    "memory_info": lambda a: _memory_info(a),
    "disk_info": lambda a: _disk_info(a),
    "network_traffic": lambda a: _network_traffic(a),
    "io_stats": lambda a: _io_stats(a),
    "reboot_host": lambda a: _run(a, "reboot 2>&1; echo 'Reboot initiated'"),
}

app = FastAPI(title="debian-mcp")

MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

@app.middleware("http")
async def auth_middleware(request, call_next):
    if MCP_API_KEY:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {MCP_API_KEY}":
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)

class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int = 1
    method: str
    params: dict = {}

@app.post("/mcp")
async def handle_mcp(req: MCPRequest):
    if req.method == "tools/list":
        return {"jsonrpc": "2.0", "result": {"tools": TOOLS}, "id": req.id}
    elif req.method == "tools/call":
        name = req.params.get("name", "")
        args = req.params.get("arguments", {})
        func = TOOL_FUNCS.get(name)
        if func:
            try:
                result = func(args)
                return {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": str(result)}]}, "id": req.id}
            except Exception as e:
                return {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": req.id}
        return {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Tool not found: {name}"}, "id": req.id}
    return {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Method not found: {req.method}"}, "id": req.id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MCP_PORT", 8003)), workers=4)
