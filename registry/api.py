import os, httpx, asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/api/registry", tags=["registry"])


class MCPServer(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    url: Optional[str] = None
    status: str = "stopped"
    platform: str = "local"
    capabilities: List[str] = []


_server_registry: dict[str, dict] = {
    "file-mcp": {
        "id": 1,
        "name": "file-mcp",
        "description": "File operations MCP",
        "url": os.getenv("FILE_MCP_URL", "http://localhost:8001"),
        "status": "running",
        "platform": "local",
        "capabilities": [],
    },
    "shell-mcp": {
        "id": 2,
        "name": "shell-mcp",
        "description": "Controlled shell execution",
        "url": os.getenv("SHELL_MCP_URL", "http://localhost:8002"),
        "status": "running",
        "platform": "local",
        "capabilities": [],
    },
    "debian-mcp": {
        "id": 3,
        "name": "debian-mcp",
        "description": "Debian server management (APT, systemd, UFW, logs)",
        "url": os.getenv("DEBIAN_MCP_URL", "http://localhost:8003"),
        "status": "running",
        "platform": "docker",
        "capabilities": [],
    },
    "sysadmin-agent": {
        "id": 4,
        "name": "sysadmin-agent",
        "description": "Debian server sysadmin: update, monitor, service management",
        "url": os.getenv("SYSADMIN_AGENT_URL", "http://localhost:8010"),
        "status": "running",
        "platform": "local",
        "capabilities": [],
    },
    "devops-agent": {
        "id": 5,
        "name": "devops-agent",
        "description": "DevOps: deploy, containers, system health",
        "url": os.getenv("DEVOPS_AGENT_URL", "http://localhost:8011"),
        "status": "running",
        "platform": "local",
        "capabilities": [],
    },
    "secops-agent": {
        "id": 6,
        "name": "secops-agent",
        "description": "Security operations: firewall, audit, compliance",
        "url": os.getenv("SECOPS_AGENT_URL", "http://localhost:8012"),
        "status": "running",
        "platform": "local",
        "capabilities": [],
    },
    "orchestrator-agent": {
        "id": 7,
        "name": "orchestrator-agent",
        "description": "LLM-powered orchestrator: plans and executes tasks using all agents",
        "url": os.getenv("ORCHESTRATOR_AGENT_URL", "http://localhost:8013"),
        "status": "running",
        "platform": "local",
        "capabilities": [],
    },
    "monitor-agent": {
        "id": 8,
        "name": "monitor-agent",
        "description": "System monitoring: CPU, memory, disk, services, logs on all hosts",
        "url": os.getenv("MONITOR_AGENT_URL", "http://localhost:8014"),
        "status": "running",
        "platform": "local",
        "capabilities": [],
    },
    "vcenter-mcp": {
        "id": 9,
        "name": "vcenter-mcp",
        "description": "vCenter VM management (power, deploy, snapshots, resources)",
        "url": os.getenv("VCENTER_MCP_URL", "http://localhost:8006"),
        "status": "running",
        "platform": "local",
        "capabilities": [],
    },
    "vcenter-agent": {
        "id": 10,
        "name": "vcenter-agent",
        "description": "vCenter agent: list VMs, power on/off, deploy, snapshots, resource monitor",
        "url": os.getenv("VCENTER_AGENT_URL", "http://localhost:8016"),
        "status": "running",
        "platform": "local",
        "capabilities": [],
    },
}


async def _refresh_capabilities():
    for name, server in _server_registry.items():
        url = server.get("url")
        if not url:
            continue
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.post(f"{url}/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1})
                if resp.status_code == 200:
                    tools = resp.json().get("result", {}).get("tools", [])
                    server["capabilities"] = [t["name"] for t in tools]
                    server["status"] = "running"
                else:
                    server["status"] = "error"
        except Exception:
            server["status"] = "stopped"


_last_refresh: float = 0

@router.get("/servers", response_model=List[MCPServer])
async def list_servers():
    global _last_refresh
    now = asyncio.get_event_loop().time()
    if now - _last_refresh > 5:
        await _refresh_capabilities()
        _last_refresh = now
    return [MCPServer(**v) for v in _server_registry.values()]


@router.get("/servers/{name}", response_model=MCPServer)
async def get_server(name: str):
    server = _server_registry.get(name)
    if not server:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    return MCPServer(**server)


@router.post("/servers", response_model=MCPServer)
async def register_server(server: MCPServer):
    if server.name in _server_registry:
        raise HTTPException(status_code=409, detail=f"Server '{server.name}' already exists")
    _server_registry[server.name] = server.model_dump()
    return server


@router.delete("/servers/{name}")
async def unregister_server(name: str):
    if name not in _server_registry:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    del _server_registry[name]
    return {"status": "deleted", "name": name}


@router.get("/health")
async def registry_health():
    return {
        "status": "healthy",
        "service": "MCP Registry",
        "server_count": len(_server_registry),
    }


def get_server_url(name: str) -> Optional[str]:
    server = _server_registry.get(name)
    return server.get("url") if server else None
