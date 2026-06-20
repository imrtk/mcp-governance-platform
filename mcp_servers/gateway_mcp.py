import os, json, httpx, urllib.parse, shutil
from pathlib import Path
from mcp.server import FastMCP
from agent_os.mcp_gateway import MCPGateway, GovernancePolicy, ApprovalStatus, ResponsePolicy
from agent_os.integrations.base import PatternType

FILE_MCP_URL = os.getenv("FILE_MCP_URL", "http://127.0.0.1:8001/mcp")
SHELL_MCP_URL = os.getenv("SHELL_MCP_URL", "http://127.0.0.1:8002/mcp")
DEBIAN_MCP_URL = os.getenv("DEBIAN_MCP_URL", "http://127.0.0.1:8003/mcp")
DO_MCP_URL = os.getenv("DO_MCP_URL", "http://127.0.0.1:8005/mcp")
GOV_API_URL = os.getenv("GOV_API_URL", "http://127.0.0.1:8080")
MCP_API_KEY = os.getenv("MCP_API_KEY", "")

TODO_FILE = Path(os.getenv("TODO_FILE", str(Path.home() / ".gov_todos.json")))

DESTRUCTIVE_COMMANDS = [
    "init 0", "init 6", "shutdown", "poweroff", "halt", "reboot",
    "rm -rf", "mkfs", "dd if=", "fdisk", " parted", "mkswap",
    "chmod 777 /", "chown -R", "> /dev/sd", ":(){ :|:& };:",
    "wget -O /", "curl -o /", "mv /", "cp /",
]

def _check_destructive_command(tool_name: str, params: dict) -> tuple[bool, str]:
    if tool_name in ("reboot_host",):
        return False, "reboot_host is blocked by central policy"
    if tool_name in ("ssh_exec", "run_shell"):
        command = params.get("command", "")
        for pattern in DESTRUCTIVE_COMMANDS:
            if pattern in command.lower():
                return False, f"Destructive command blocked: pattern '{pattern}' detected in command"
        if command.strip().startswith("sudo "):
            return False, "sudo commands are not allowed via SSH/shell"
    return True, ""

policy = GovernancePolicy(
    name="vibe-gateway-policy",
    max_tool_calls=200,
    allowed_tools=[
        "list_dir", "read_file", "write_file", "search_files", "grep",
        "run_shell", "web_fetch", "web_search", "todo",
        "system_info", "uptime", "disk_usage", "process_list",
        "list_hosts", "ssh_exec",
        "deb_update", "deb_upgrade", "deb_install", "deb_remove", "deb_search",
        "deb_list_upgradable", "deb_autoremove",
        "service_status", "service_restart", "service_start", "service_stop", "service_enable",
        "journalctl", "ufw_status", "ufw_allow", "reboot_host", "network",
        "list_droplets", "droplet_status", "power_on", "power_off", "ensure_running", "reboot_droplet", "ensure_all_running",
        "orchestrate",
    ],
    blocked_patterns=[
        (r";\s*(rm|del)\b", PatternType.REGEX),
        (r"\b(init 0|init 6|poweroff|shutdown|halt|sudo (init|poweroff|shutdown|halt))\b", PatternType.REGEX),
    ],
    log_all_calls=True,
)

gateway = MCPGateway(
    policy,
    denied_tools=["delete"],
    sensitive_tools=["write_file", "deb_install", "deb_remove", "deb_upgrade",
                      "service_restart", "service_stop", "reboot_host"],
    approval_callback=lambda aid, tn, p: ApprovalStatus.APPROVED,
    enable_builtin_sanitization=False,
    response_policy=ResponsePolicy.LOG,
)

mcp = FastMCP("governance-gateway")

def _load_todos() -> list:
    if TODO_FILE.exists():
        return json.loads(TODO_FILE.read_text())
    return []

def _send_audit(agent_id: str, tool_name: str, params: dict, allowed: bool, reason: str):
    try:
        import threading as _thr
        def _post():
            try:
                httpx.post(f"{GOV_API_URL}/api/gateway/audit/ingest", json={
                    "timestamp": __import__("time").time(),
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                    "parameters": params,
                    "allowed": allowed,
                    "reason": reason,
                }, timeout=2)
            except Exception:
                pass
        _thr.Thread(target=_post, daemon=True).start()
    except Exception:
        pass

# Wrap gateway.intercept_tool_call to also send audit + destructive command check
_original_intercept = gateway.intercept_tool_call
def _audited_intercept(agent_id, tool_name, params):
    safe, reason = _check_destructive_command(tool_name, params)
    if not safe:
        _send_audit(agent_id, tool_name, dict(params), False, reason)
        return False, reason
    allowed, reason = _original_intercept(agent_id, tool_name, params)
    _send_audit(agent_id, tool_name, dict(params), allowed, reason)
    return allowed, reason
gateway.intercept_tool_call = _audited_intercept

def _save_todos(todos: list):
    TODO_FILE.write_text(json.dumps(todos, indent=2))

def _proxy_to(url: str, tool_name: str, arguments: dict) -> str:
    payload = {
        "jsonrpc": "2.0", "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}, "id": 1,
    }
    headers = {"Content-Type": "application/json"}
    if MCP_API_KEY:
        headers["Authorization"] = f"Bearer {MCP_API_KEY}"
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("result", {}).get("content", [])
        return content[0]["text"] if content else str(data)
    except Exception as e:
        return f"[PROXY ERROR] {e}"

def _local_backend(tool: str, args: dict) -> str:
    return _proxy_to(FILE_MCP_URL, tool, args)

def _remote_backend(tool: str, args: dict) -> str:
    return _proxy_to(DEBIAN_MCP_URL, tool, args)

def _is_remote(args: dict) -> bool:
    return bool(args.get("host_name") or args.get("host"))

# ── File operations (local only) ──

@mcp.tool()
def list_dir(path: str = ".") -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "list_dir", {"path": path})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _local_backend("list_dir", {"path": path})

@mcp.tool()
def read_file(path: str) -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "read_file", {"path": path})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    result = _local_backend("read_file", {"path": path})
    scan = gateway.intercept_tool_response("vibe", "read_file", result)
    if not scan.allowed: return f"[GOVERNANCE DENIED] Response blocked: {scan.reason}"
    return result

@mcp.tool()
def write_file(path: str, content: str) -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "write_file", {"path": path, "content": content})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _local_backend("write_file", {"path": path, "content": content})

@mcp.tool()
def search_files(pattern: str, path: str = ".") -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "search_files", {"pattern": pattern, "path": path})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _local_backend("search_files", {"pattern": pattern, "path": path})

@mcp.tool()
def grep(pattern: str, path: str = ".") -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "grep", {"pattern": pattern, "path": path})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _local_backend("grep", {"pattern": pattern, "path": path})

@mcp.tool()
def run_shell(command: str, timeout: int = 30) -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "run_shell", {"command": command, "timeout": timeout})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    result = _proxy_to(SHELL_MCP_URL, "run_shell", {"command": command, "timeout": timeout})
    scan = gateway.intercept_tool_response("vibe", "run_shell", result)
    if not scan.allowed: return f"[GOVERNANCE DENIED] Response blocked: {scan.reason}"
    return result

# ── System tools (local + remote dual mode) ──

@mcp.tool()
def system_info(host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port}
    allowed, reason = gateway.intercept_tool_call("vibe", "system_info", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    if _is_remote(args):
        return _remote_backend("system_info", args)
    import platform, shutil
    total, used, free = shutil.disk_usage("/")
    info = {"hostname": platform.node(), "os": platform.system(), "release": platform.release(),
            "cpu_count": os.cpu_count(), "disk_gb": {"total": round(total/1024**3,1), "free": round(free/1024**3,1)}}
    result = json.dumps(info)
    scan = gateway.intercept_tool_response("vibe", "system_info", result)
    if not scan.allowed: return f"[GOVERNANCE DENIED] Response blocked: {scan.reason}"
    return result

@mcp.tool()
def uptime(host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port}
    allowed, reason = gateway.intercept_tool_call("vibe", "uptime", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    if _is_remote(args):
        return _remote_backend("uptime", args)
    try:
        with open("/proc/uptime") as f:
            s = float(f.read().split()[0])
        return f"Up {int(s//86400)}d {int((s%86400)//3600)}h {int((s%3600)//60)}m"
    except Exception as e:
        return f"[ERROR] {e}"

@mcp.tool()
def disk_usage(path: str = "/", host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port}
    allowed, reason = gateway.intercept_tool_call("vibe", "disk_usage", {"path": path, **args})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    if _is_remote(args):
        return _remote_backend("disk_usage", args)
    try:
        t, u, f = shutil.disk_usage(path)
        result = json.dumps({"path": path, "total_gb": round(t/1024**3,1), "free_gb": round(f/1024**3,1)})
        return result
    except Exception as e:
        return f"[ERROR] {e}"

@mcp.tool()
def process_list(host_name: str = "", host: str = "", user: str = "", port: int = 22, sort: str = "cpu", count: int = 10) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "sort": sort, "count": count}
    allowed, reason = gateway.intercept_tool_call("vibe", "process_list", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    if _is_remote(args):
        return _remote_backend("process_list", args)
    import subprocess
    flag = "%CPU" if sort == "cpu" else "%MEM"
    try:
        result = subprocess.run(["ps", f"axo", "pid,user,%cpu,%mem,comm", f"--sort=-{flag}"],
                                capture_output=True, text=True, timeout=10)
        return "\n".join(result.stdout.strip().split("\n")[:count + 1])
    except Exception as e:
        return f"[ERROR] {e}"

# ── Remote host management (debian-mcp) ──

@mcp.tool()
def list_hosts() -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "list_hosts", {})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("list_hosts", {})

@mcp.tool()
def ssh_exec(host_name: str = "", host: str = "", user: str = "", port: int = 22, command: str = "") -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "command": command}
    allowed, reason = gateway.intercept_tool_call("vibe", "ssh_exec", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    result = _remote_backend("ssh_exec", args)
    scan = gateway.intercept_tool_response("vibe", "ssh_exec", result)
    if not scan.allowed: return f"[GOVERNANCE DENIED] Response blocked: {scan.reason}"
    return result

@mcp.tool()
def deb_update(host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port}
    allowed, reason = gateway.intercept_tool_call("vibe", "deb_update", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("deb_update", args)

@mcp.tool()
def deb_upgrade(host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port}
    allowed, reason = gateway.intercept_tool_call("vibe", "deb_upgrade", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("deb_upgrade", args)

@mcp.tool()
def deb_install(packages: str, host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "packages": packages}
    allowed, reason = gateway.intercept_tool_call("vibe", "deb_install", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("deb_install", args)

@mcp.tool()
def deb_remove(packages: str, host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "packages": packages}
    allowed, reason = gateway.intercept_tool_call("vibe", "deb_remove", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("deb_remove", args)

@mcp.tool()
def deb_search(query: str, host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "query": query}
    allowed, reason = gateway.intercept_tool_call("vibe", "deb_search", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("deb_search", args)

@mcp.tool()
def deb_list_upgradable(host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port}
    allowed, reason = gateway.intercept_tool_call("vibe", "deb_list_upgradable", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("deb_list_upgradable", args)

@mcp.tool()
def deb_autoremove(host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port}
    allowed, reason = gateway.intercept_tool_call("vibe", "deb_autoremove", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("deb_autoremove", args)

@mcp.tool()
def service_status(service: str, host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "service": service}
    allowed, reason = gateway.intercept_tool_call("vibe", "service_status", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("service_status", args)

@mcp.tool()
def service_restart(service: str, host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "service": service}
    allowed, reason = gateway.intercept_tool_call("vibe", "service_restart", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("service_restart", args)

@mcp.tool()
def service_start(service: str, host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "service": service}
    allowed, reason = gateway.intercept_tool_call("vibe", "service_start", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("service_start", args)

@mcp.tool()
def service_stop(service: str, host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "service": service}
    allowed, reason = gateway.intercept_tool_call("vibe", "service_stop", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("service_stop", args)

@mcp.tool()
def service_enable(service: str, host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "service": service}
    allowed, reason = gateway.intercept_tool_call("vibe", "service_enable", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("service_enable", args)

@mcp.tool()
def journalctl(host_name: str = "", host: str = "", user: str = "", port: int = 22, service: str = "", lines: int = 50) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "service": service, "lines": lines}
    allowed, reason = gateway.intercept_tool_call("vibe", "journalctl", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("journalctl", args)

@mcp.tool()
def ufw_status(host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port}
    allowed, reason = gateway.intercept_tool_call("vibe", "ufw_status", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("ufw_status", args)

@mcp.tool()
def ufw_allow(rule: str, host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "rule": rule}
    allowed, reason = gateway.intercept_tool_call("vibe", "ufw_allow", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("ufw_allow", args)

@mcp.tool()
def reboot_host(host_name: str = "", host: str = "", user: str = "", port: int = 22) -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port}
    allowed, reason = gateway.intercept_tool_call("vibe", "reboot_host", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("reboot_host", args)

@mcp.tool()
def network(host_name: str = "", host: str = "", user: str = "", port: int = 22, action: str = "ping", target: str = "") -> str:
    args = {"host_name": host_name, "host": host, "user": user, "port": port, "action": action, "target": target}
    allowed, reason = gateway.intercept_tool_call("vibe", "network", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _remote_backend("network", args)

# ── DigitalOcean droplet management ──

@mcp.tool()
def list_droplets() -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "list_droplets", {})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _proxy_to(DO_MCP_URL, "list_droplets", {})

@mcp.tool()
def droplet_status(name: str = "", droplet_name: str = "") -> str:
    args = {"name": name, "droplet_name": droplet_name}
    allowed, reason = gateway.intercept_tool_call("vibe", "droplet_status", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _proxy_to(DO_MCP_URL, "droplet_status", args)

@mcp.tool()
def power_on(name: str = "", droplet_name: str = "") -> str:
    args = {"name": name, "droplet_name": droplet_name}
    allowed, reason = gateway.intercept_tool_call("vibe", "power_on", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _proxy_to(DO_MCP_URL, "power_on", args)

@mcp.tool()
def power_off(name: str = "", droplet_name: str = "") -> str:
    args = {"name": name, "droplet_name": droplet_name}
    allowed, reason = gateway.intercept_tool_call("vibe", "power_off", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _proxy_to(DO_MCP_URL, "power_off", args)

@mcp.tool()
def ensure_running(name: str = "", droplet_name: str = "", wait_seconds: int = 30) -> str:
    args = {"name": name, "droplet_name": droplet_name, "wait_seconds": wait_seconds}
    allowed, reason = gateway.intercept_tool_call("vibe", "ensure_running", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _proxy_to(DO_MCP_URL, "ensure_running", args)

@mcp.tool()
def reboot_droplet(name: str = "", droplet_name: str = "") -> str:
    args = {"name": name, "droplet_name": droplet_name}
    allowed, reason = gateway.intercept_tool_call("vibe", "reboot_droplet", args)
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    return _proxy_to(DO_MCP_URL, "reboot_droplet", args)

# ── Web / utility tools (built-in) ──

@mcp.tool()
def web_fetch(url: str) -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "web_fetch", {"url": url})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        text = resp.text[:10000]
        scan = gateway.intercept_tool_response("vibe", "web_fetch", text)
        if not scan.allowed: return f"[GOVERNANCE DENIED] Response blocked: {scan.reason}"
        return text
    except Exception as e:
        return f"[ERROR] {e}"

@mcp.tool()
def web_search(query: str) -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "web_search", {"query": query})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        resp = httpx.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        text = resp.text[:10000]
        scan = gateway.intercept_tool_response("vibe", "web_search", text)
        if not scan.allowed: return f"[GOVERNANCE DENIED] Response blocked: {scan.reason}"
        return text
    except Exception as e:
        return f"[ERROR] {e}"

@mcp.tool()
def todo(action: str, content: str = "") -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "todo", {"action": action, "content": content})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    todos = _load_todos()
    if action == "list":
        return json.dumps(todos, indent=2) if todos else "No todos"
    elif action == "add":
        todos.append({"id": len(todos) + 1, "content": content, "done": False})
        _save_todos(todos)
        return f"Added: {content}"
    elif action == "done":
        for t in todos:
            if not t["done"]:
                t["done"] = True
                _save_todos(todos)
                return f"Marked done: {t['content']}"
        return "No pending todos"
    elif action == "clear":
        _save_todos([])
        return "All todos cleared"
    return "Invalid action. Use: list, add, done, clear"

@mcp.tool()
def orchestrate(task: str) -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "orchestrate", {"task": task[:80]})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    try:
        resp = httpx.post(
            f"{GOV_API_URL}/api/gateway/agent/orchestrator-agent/ask",
            json={"tool_name": "ask", "params": {"task": task}},
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("result", {}).get("content", [{}])
        return content[0].get("text", str(data)) if content else str(data)
    except Exception as e:
        return f"[ORCHESTRATOR ERROR] {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
