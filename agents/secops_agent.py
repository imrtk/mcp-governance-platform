"""SecOps Agent: Security monitoring, firewall, audit, and compliance checks."""
import os
from agents.base_agent import BaseAgent

TOOLS = [
    {
        "name": "firewall_status",
        "description": "Check firewall (UFW/iptables) status on a host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
            },
            "required": ["host_name"],
        },
    },
    {
        "name": "open_ports",
        "description": "List listening ports and their services on a host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
            },
            "required": ["host_name"],
        },
    },
    {
        "name": "failed_logins",
        "description": "Show recent failed SSH login attempts (auth.log/journalctl)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "lines": {"type": "integer", "description": "Number of lines", "default": 20},
            },
            "required": ["host_name"],
        },
    },
    {
        "name": "security_audit",
        "description": "Run a quick security audit: open ports, firewall, failed logins, running services",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
            },
            "required": ["host_name"],
        },
    },
    {
        "name": "allow_port",
        "description": "Open a port in UFW firewall on a host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "port": {"type": "string", "description": "Port or service (e.g. 443/tcp, OpenSSH)"},
            },
            "required": ["host_name", "port"],
        },
    },
    {
        "name": "ask_sysadmin",
        "description": "Delegate a host operation to the sysadmin agent",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "task": {"type": "string", "description": "sysadmin tool name"},
                "params": {"type": "object", "description": "Additional parameters", "default": {}},
            },
            "required": ["host_name", "task"],
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


def _firewall_status(args: dict) -> str:
    host = args.get("host_name", "")
    lines = []
    lines.append("=== UFW Status ===")
    lines.append(_call("debian-mcp", "ufw_status", {"host_name": host}))
    lines.append("")
    lines.append("=== iptables ===")
    lines.append(_call("debian-mcp", "network", {"host_name": host, "action": "ports"}))
    return "\n".join(lines)


def _open_ports(args: dict) -> str:
    host = args.get("host_name", "")
    return _call("debian-mcp", "network", {"host_name": host, "action": "ports"})


def _failed_logins(args: dict) -> str:
    host = args.get("host_name", "")
    lines_count = args.get("lines", 20)
    result = _call("debian-mcp", "journalctl", {"host_name": host, "service": "ssh", "lines": lines_count})
    failed = [l for l in result.split("\n") if "Failed password" in l]
    if failed:
        return f"Recent failed logins ({len(failed)} entries):\n" + "\n".join(failed[-lines_count:])
    return "No recent failed login attempts found."


def _security_audit(args: dict) -> str:
    host = args.get("host_name", "")
    lines = []
    lines.append("╔══════════════════════════════════════╗")
    lines.append("║        Security Audit Report         ║")
    lines.append("╚══════════════════════════════════════╝")
    lines.append("")
    lines.append("=== Open Ports ===")
    lines.append(_call("debian-mcp", "network", {"host_name": host, "action": "ports"}))
    lines.append("")
    lines.append("=== Firewall ===")
    lines.append(_call("debian-mcp", "ufw_status", {"host_name": host}))
    lines.append("")
    lines.append("=== Failed Logins ===")
    lines.append(_failed_logins(args))
    lines.append("")
    lines.append("=== Running Services ===")
    result = _call("debian-mcp", "journalctl", {"host_name": host, "service": "", "lines": 5})
    services = _call("debian-mcp", "process_list", {"host_name": host, "sort": "cpu", "count": 15})
    lines.append(services)
    return "\n".join(lines)


def _allow_port(args: dict) -> str:
    host = args.get("host_name", "")
    port = args.get("port", "")
    return _call("debian-mcp", "ufw_allow", {"host_name": host, "rule": port})


def _ask_sysadmin(args: dict) -> str:
    agent = _get_agent()
    host_name = args.get("host_name", "")
    task = args.get("task", "")
    params = args.get("params", {})
    params["host_name"] = host_name
    return agent.ask_agent("sysadmin-agent", task, params)


TOOL_FUNCS = {
    "firewall_status": _firewall_status,
    "open_ports": _open_ports,
    "failed_logins": _failed_logins,
    "security_audit": _security_audit,
    "allow_port": _allow_port,
    "ask_sysadmin": _ask_sysadmin,
}

if __name__ == "__main__":
    port = int(os.getenv("SECOPS_AGENT_PORT", "8012"))
    agent = BaseAgent(
        name="secops-agent",
        description="Security operations: firewall, audit, port scanning, compliance",
        tools=TOOLS,
        tool_funcs=TOOL_FUNCS,
        port=port,
        platform="local",
    )
    _agent_instance = agent
    agent.run()
