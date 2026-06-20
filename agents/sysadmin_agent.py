"""Sysadmin Agent: Debian server management, monitoring, and orchestration."""
import os
from agents.base_agent import BaseAgent

TOOLS = [
    {
        "name": "host_status",
        "description": "Get full status summary for a host (uptime, CPU, memory, disk, load)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
            },
            "required": ["host_name"],
        },
    },
    {
        "name": "update_all",
        "description": "Run apt update + upgrade + autoremove on a host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
            },
            "required": ["host_name"],
        },
    },
    {
        "name": "restart_service",
        "description": "Restart a systemd service and verify its status",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "service": {"type": "string", "description": "Service name"},
            },
            "required": ["host_name", "service"],
        },
    },
    {
        "name": "disk_alert",
        "description": "Check disk usage and report if any mount is above threshold",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "threshold": {"type": "integer", "description": "Usage percent threshold", "default": 80},
            },
            "required": ["host_name"],
        },
    },
    {
        "name": "top_processes",
        "description": "Show top CPU and memory consuming processes on a host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
            },
            "required": ["host_name"],
        },
    },
    {
        "name": "list_hosts",
        "description": "List configured hosts and their status",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "call_debian",
        "description": "Directly call any debian-mcp tool on a host (low-level access)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "tool": {"type": "string", "description": "debian-mcp tool name (deb_install, service_status, cpu_usage, etc)"},
                "params": {"type": "object", "description": "Tool parameters", "default": {}},
            },
            "required": ["host_name", "tool"],
        },
    },
]


def _call(mcp: str, tool: str, params: dict) -> str:
    agent = _get_agent()
    return agent._call_gateway(tool, params, mcp)


_agent_instance = None


def _get_agent():
    global _agent_instance
    return _agent_instance


def _host_status(args: dict) -> str:
    host = args.get("host_name", "")
    return _call("debian-mcp", "system_info", {"host_name": host})


def _update_all(args: dict) -> str:
    host = args.get("host_name", "")
    lines = []
    lines.append("=== apt update ===")
    lines.append(_call("debian-mcp", "deb_update", {"host_name": host}))
    lines.append("")
    lines.append("=== apt upgrade ===")
    lines.append(_call("debian-mcp", "deb_upgrade", {"host_name": host}))
    lines.append("")
    lines.append("=== autoremove ===")
    lines.append(_call("debian-mcp", "deb_autoremove", {"host_name": host}))
    return "\n".join(lines)


def _restart_service(args: dict) -> str:
    host = args.get("host_name", "")
    svc = args.get("service", "")
    result = _call("debian-mcp", "service_restart", {"host_name": host, "service": svc})
    status = _call("debian-mcp", "service_status", {"host_name": host, "service": svc})
    return f"{result}\n\n{status}"


def _disk_alert(args: dict) -> str:
    host = args.get("host_name", "")
    threshold = args.get("threshold", 80)
    raw = _call("debian-mcp", "disk_usage", {"host_name": host})
    alerts = []
    for line in raw.split("\n"):
        parts = line.split()
        if len(parts) >= 5 and parts[4].endswith("%"):
            try:
                pct = int(parts[4][:-1])
                if pct >= threshold:
                    alerts.append(f"WARNING: {parts[5]} at {parts[4]} used")
            except ValueError:
                pass
    if not alerts:
        return f"All mounts below {threshold}% usage.\n\n{raw}"
    return "\n".join(alerts) + f"\n\n{raw}"


def _top_processes(args: dict) -> str:
    host = args.get("host_name", "")
    lines = []
    lines.append("=== Top CPU ===")
    lines.append(_call("debian-mcp", "process_list", {"host_name": host, "sort": "cpu", "count": 10}))
    lines.append("")
    lines.append("=== Top Memory ===")
    lines.append(_call("debian-mcp", "process_list", {"host_name": host, "sort": "memory", "count": 10}))
    return "\n".join(lines)


def _list_hosts(args: dict) -> str:
    return _call("debian-mcp", "list_hosts", {})


def _call_debian(args: dict) -> str:
    host = args.get("host_name", "")
    tool = args.get("tool", "")
    params = args.get("params", {})
    params["host_name"] = host
    return _call("debian-mcp", tool, params)


TOOL_FUNCS = {
    "host_status": _host_status,
    "update_all": _update_all,
    "restart_service": _restart_service,
    "disk_alert": _disk_alert,
    "top_processes": _top_processes,
    "list_hosts": _list_hosts,
    "call_debian": _call_debian,
}

if __name__ == "__main__":
    port = int(os.getenv("SYSADMIN_AGENT_PORT", "8010"))
    agent = BaseAgent(
        name="sysadmin-agent",
        description="Debian server sysadmin: update, monitor, service management",
        tools=TOOLS,
        tool_funcs=TOOL_FUNCS,
        port=port,
        platform="local",
    )
    _agent_instance = agent
    agent.run()
