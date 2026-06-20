"""DO Agent: DigitalOcean droplet management via do-mcp."""
import os
from agents.base_agent import BaseAgent

MCP_NAME = "do-mcp"

TOOLS = [
    {
        "name": "list_droplets",
        "description": "List all DigitalOcean droplets with status, IP, region, specs",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "droplet_status",
        "description": "Get detailed status of a specific droplet (power, IP, region, specs)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Droplet name"},
                "droplet_name": {"type": "string", "description": "Droplet name (alias)"},
            },
            "required": [],
        },
    },
    {
        "name": "power_on",
        "description": "Power on a droplet that is currently off",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Droplet name"},
                "droplet_name": {"type": "string", "description": "Droplet name (alias)"},
            },
            "required": [],
        },
    },
    {
        "name": "power_off",
        "description": "Power off a running droplet",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Droplet name"},
                "droplet_name": {"type": "string", "description": "Droplet name (alias)"},
            },
            "required": [],
        },
    },
    {
        "name": "ensure_running",
        "description": "Check if a droplet is running; if off, power it on and wait for it to become active",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Droplet name"},
                "droplet_name": {"type": "string", "description": "Droplet name (alias)"},
                "wait_seconds": {"type": "integer", "description": "Seconds to wait for power-on", "default": 30},
            },
            "required": [],
        },
    },
    {
        "name": "reboot_droplet",
        "description": "Reboot a running droplet",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Droplet name"},
                "droplet_name": {"type": "string", "description": "Droplet name (alias)"},
            },
            "required": [],
        },
    },
    {
        "name": "ensure_all_running",
        "description": "Check all droplets and power on any that are off",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_agent_instance = None


def _get_agent():
    global _agent_instance
    return _agent_instance


def _call(tool: str, params: dict) -> str:
    agent = _get_agent()
    return agent._call_gateway(tool, params, MCP_NAME)


def _list_droplets(args: dict) -> str:
    return _call("list_droplets", {})


def _droplet_status(args: dict) -> str:
    name = args.get("name") or args.get("droplet_name") or ""
    return _call("droplet_status", {"name": name, "droplet_name": name})


def _power_on(args: dict) -> str:
    name = args.get("name") or args.get("droplet_name") or ""
    return _call("power_on", {"name": name, "droplet_name": name})


def _power_off(args: dict) -> str:
    name = args.get("name") or args.get("droplet_name") or ""
    return _call("power_off", {"name": name, "droplet_name": name})


def _ensure_running(args: dict) -> str:
    name = args.get("name") or args.get("droplet_name") or ""
    wait = args.get("wait_seconds", 30)
    return _call("ensure_running", {"name": name, "droplet_name": name, "wait_seconds": wait})


def _reboot_droplet(args: dict) -> str:
    name = args.get("name") or args.get("droplet_name") or ""
    return _call("reboot_droplet", {"name": name, "droplet_name": name})


def _ensure_all_running(args: dict) -> str:
    raw = _call("list_droplets", {})
    lines = raw.split("\n")
    results = []
    for line in lines:
        parts = line.strip().split()
        if len(parts) >= 2:
            dname = parts[0]
            status = parts[1] if len(parts) > 1 else ""
            if status == "off":
                r = _call("ensure_running", {"name": dname, "wait_seconds": 60})
                results.append(f"{dname}: {r}")
            else:
                results.append(f"{dname}: already {status}")
    return "\n".join(results) if results else raw


TOOL_FUNCS = {
    "list_droplets": _list_droplets,
    "droplet_status": _droplet_status,
    "power_on": _power_on,
    "power_off": _power_off,
    "ensure_running": _ensure_running,
    "reboot_droplet": _reboot_droplet,
    "ensure_all_running": _ensure_all_running,
}

if __name__ == "__main__":
    port = int(os.getenv("DO_AGENT_PORT", "8015"))
    agent = BaseAgent(
        name="do-agent",
        description="DigitalOcean droplet management: power on/off/status for all droplets",
        tools=TOOLS,
        tool_funcs=TOOL_FUNCS,
        port=port,
        platform="local",
    )
    _agent_instance = agent
    agent.run()
