import os, json, httpx, urllib.parse, shutil, platform, subprocess
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path
from mcp.server import FastMCP
from agent_os.mcp_gateway import MCPGateway, GovernancePolicy, ApprovalStatus, ResponsePolicy
from agent_os.integrations.base import PatternType

GOV_API_URL = os.getenv("GOV_API_URL", "http://127.0.0.1:8080")
MCP_API_KEY = os.getenv("MCP_API_KEY", "")

TODO_FILE = Path(os.getenv("TODO_FILE", str(Path.home() / ".gov_todos.json")))

policy = GovernancePolicy(
    name="vibe-gateway-policy",
    max_tool_calls=200,
    allowed_tools=[
        "system_info", "uptime", "disk_usage", "process_list",
        "web_fetch", "web_search", "todo",
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
    sensitive_tools=[],
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

_original_intercept = gateway.intercept_tool_call
def _audited_intercept(agent_id, tool_name, params):
    allowed, reason = _original_intercept(agent_id, tool_name, params)
    _send_audit(agent_id, tool_name, dict(params), allowed, reason)
    return allowed, reason
gateway.intercept_tool_call = _audited_intercept

def _save_todos(todos: list):
    TODO_FILE.write_text(json.dumps(todos, indent=2))

# ── System tools (local only) ──

@mcp.tool()
def system_info() -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "system_info", {})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    total, used, free = shutil.disk_usage("/")
    info = {"hostname": platform.node(), "os": platform.system(), "release": platform.release(),
            "cpu_count": os.cpu_count(), "disk_gb": {"total": round(total/1024**3,1), "free": round(free/1024**3,1)}}
    result = json.dumps(info)
    scan = gateway.intercept_tool_response("vibe", "system_info", result)
    if not scan.allowed: return f"[GOVERNANCE DENIED] Response blocked: {scan.reason}"
    return result

@mcp.tool()
def uptime() -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "uptime", {})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    try:
        with open("/proc/uptime") as f:
            s = float(f.read().split()[0])
        return f"Up {int(s//86400)}d {int((s%86400)//3600)}h {int((s%3600)//60)}m"
    except Exception as e:
        return f"[ERROR] {e}"

@mcp.tool()
def disk_usage(path: str = "/") -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "disk_usage", {"path": path})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    try:
        t, u, f = shutil.disk_usage(path)
        result = json.dumps({"path": path, "total_gb": round(t/1024**3,1), "free_gb": round(f/1024**3,1)})
        return result
    except Exception as e:
        return f"[ERROR] {e}"

@mcp.tool()
def process_list(sort: str = "cpu", count: int = 10) -> str:
    allowed, reason = gateway.intercept_tool_call("vibe", "process_list", {"sort": sort, "count": count})
    if not allowed: return f"[GOVERNANCE DENIED] {reason}"
    flag = "%CPU" if sort == "cpu" else "%MEM"
    try:
        result = subprocess.run(["ps", f"axo", "pid,user,%cpu,%mem,comm", f"--sort=-{flag}"],
                                capture_output=True, text=True, timeout=10)
        return "\n".join(result.stdout.strip().split("\n")[:count + 1])
    except Exception as e:
        return f"[ERROR] {e}"

# ── Web / utility tools ──

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
