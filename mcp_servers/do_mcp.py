import os, json
from fastapi import FastAPI
from pydantic import BaseModel
import httpx

DO_API_TOKEN = os.environ.get("DO_API_TOKEN", "")
DO_API = "https://api.digitalocean.com/v2"
DO_PROJECT_ID = os.environ.get("DO_PROJECT_ID", "").strip()

HEADERS = {"Authorization": f"Bearer {DO_API_TOKEN}", "Content-Type": "application/json"}

_PROJECT_DROPLET_IDS: list[int] | None = None


def _get_project_droplet_ids() -> list[int]:
    global _PROJECT_DROPLET_IDS
    if _PROJECT_DROPLET_IDS is not None:
        return _PROJECT_DROPLET_IDS
    if not DO_PROJECT_ID:
        _PROJECT_DROPLET_IDS = []
        return _PROJECT_DROPLET_IDS
    try:
        r = httpx.get(f"{DO_API}/projects/{DO_PROJECT_ID}/resources", headers=HEADERS, timeout=10)
        r.raise_for_status()
        ids = []
        for res in r.json().get("resources", []):
            urn = res.get("urn", "")
            parts = urn.split(":")
            if len(parts) >= 3 and "droplet" in parts[1]:
                try:
                    ids.append(int(parts[-1]))
                except ValueError:
                    pass
        _PROJECT_DROPLET_IDS = ids
        return ids
    except Exception:
        _PROJECT_DROPLET_IDS = []
        return []


def _is_managed(droplet_id: int) -> bool:
    project_ids = _get_project_droplet_ids()
    if not project_ids:
        return True
    return droplet_id in project_ids

TOOLS = [
    {
        "name": "list_droplets",
        "description": "List all DigitalOcean droplets with status, IP, region",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "droplet_status",
        "description": "Check a specific droplet's power status",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Droplet name (e.g. hera)"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "power_on",
        "description": "Power on a droplet if it is powered off",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Droplet name"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "power_off",
        "description": "Power off a running droplet",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Droplet name"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "ensure_running",
        "description": "Check if a droplet is running; if off, power it on and wait",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Droplet name"},
                "wait_seconds": {"type": "integer", "description": "Seconds to wait for power-on", "default": 30}
            },
            "required": ["name"]
        }
    },
    {
        "name": "reboot_droplet",
        "description": "Reboot a droplet",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Droplet name"}
            },
            "required": ["name"]
        }
    },
]


def _do_get(path: str) -> dict:
    r = httpx.get(f"{DO_API}{path}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _do_post(path: str, data: dict = None) -> dict:
    r = httpx.post(f"{DO_API}{path}", headers=HEADERS, json=data or {}, timeout=15)
    r.raise_for_status()
    return r.json()


def _resolve_name(args: dict) -> str:
    return args.get("name") or args.get("droplet_name") or ""

def _find_droplet(name: str) -> dict | None:
    if not name:
        return None
    data = _do_get("/droplets")
    for d in data.get("droplets", []):
        if d["name"].lower() == name.lower() and _is_managed(d["id"]):
            return d
    return None


def _list_droplets(args: dict) -> str:
    if not DO_API_TOKEN:
        return "DO_API_TOKEN environment variable not set"
    data = _do_get("/droplets")
    droplets = data.get("droplets", [])
    if not droplets:
        return "No droplets found"
    lines = []
    for d in droplets:
        if not _is_managed(d["id"]):
            continue
        ip = next((n["ip_address"] for n in d.get("networks", {}).get("v4", [])
                   if n.get("type") == "public"), "-")
        lines.append(f"  {d['name']:15s} {d['status']:10s} {d['memory']}MB {d['vcpus']}cpu {ip}")
    if not lines:
        return "No managed droplets found. Set DO_PROJECT_ID env var."
    return "Droplets:\n" + "\n".join(lines)


def _droplet_status(args: dict) -> str:
    name = _resolve_name(args)
    d = _find_droplet(name)
    if not d:
        return f"Droplet '{name}' not found"
    ip = next((n["ip_address"] for n in d.get("networks", {}).get("v4", [])
               if n.get("type") == "public"), "-")
    return json.dumps({
        "name": d["name"],
        "status": d["status"],
        "ip": ip,
        "region": d["region"]["slug"],
        "memory_mb": d["memory"],
        "vcpus": d["vcpus"],
        "disk_gb": d["disk"],
        "created_at": d["created_at"],
    }, indent=2)


def _power_on(args: dict) -> str:
    name = _resolve_name(args)
    d = _find_droplet(name)
    if not d:
        return f"Droplet '{name}' not found"
    if d["status"] == "active":
        return f"Droplet '{name}' is already running"
    _do_post(f"/droplets/{d['id']}/actions", {"type": "power_on"})
    return f"Power-on requested for '{name}'"


def _power_off(args: dict) -> str:
    name = _resolve_name(args)
    d = _find_droplet(name)
    if not d:
        return f"Droplet '{name}' not found"
    if d["status"] == "off":
        return f"Droplet '{name}' is already off"
    _do_post(f"/droplets/{d['id']}/actions", {"type": "power_off"})
    return f"Power-off requested for '{name}'"


def _ensure_running(args: dict) -> str:
    import time
    name = _resolve_name(args)
    wait = args.get("wait_seconds", 30)
    d = _find_droplet(name)
    if not d:
        return f"Droplet '{name}' not found"
    if d["status"] == "active":
        ip = next((n["ip_address"] for n in d.get("networks", {}).get("v4", [])
                   if n.get("type") == "public"), "-")
        return f"Droplet '{name}' is already running (IP: {ip})"
    _do_post(f"/droplets/{d['id']}/actions", {"type": "power_on"})
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(5)
        d = _find_droplet(name)
        if d and d["status"] == "active":
            ip = next((n["ip_address"] for n in d.get("networks", {}).get("v4", [])
                       if n.get("type") == "public"), "-")
            return f"Droplet '{name}' powered on (IP: {ip})"
    return f"Droplet '{name}' power-on requested but not confirmed within {wait}s. Check later."


def _reboot(args: dict) -> str:
    name = _resolve_name(args)
    d = _find_droplet(name)
    if not d:
        return f"Droplet '{name}' not found"
    if d["status"] != "active":
        return f"Cannot reboot '{name}' — status is '{d['status']}'"
    _do_post(f"/droplets/{d['id']}/actions", {"type": "reboot"})
    return f"Reboot requested for '{name}'"


TOOL_FUNCS = {
    "list_droplets": _list_droplets,
    "droplet_status": _droplet_status,
    "power_on": _power_on,
    "power_off": _power_off,
    "ensure_running": _ensure_running,
    "reboot_droplet": _reboot,
}

app = FastAPI(title="do-mcp")

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
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MCP_PORT", 8005)))
