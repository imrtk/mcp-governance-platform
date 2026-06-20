"""DevOps Agent: Deployment, container management, and CI/CD operations."""
import os, json
from agents.base_agent import BaseAgent

TOOLS = [
    {
        "name": "deploy_service",
        "description": "Deploy a service: pull latest, restart, verify (uses shell-mcp for docker commands)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Remote host address"},
                "service_name": {"type": "string", "description": "Docker service or compose project name"},
                "image": {"type": "string", "description": "Docker image to deploy", "default": ""},
            },
            "required": ["host", "service_name"],
        },
    },
    {
        "name": "container_status",
        "description": "Check Docker container status on a host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
            },
            "required": ["host"],
        },
    },
    {
        "name": "logs_tail",
        "description": "Tail logs from a Docker container or service",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Remote host address"},
                "container": {"type": "string", "description": "Container name or service name"},
                "lines": {"type": "integer", "description": "Number of lines", "default": 50},
            },
            "required": ["host", "container"],
        },
    },
    {
        "name": "system_health",
        "description": "Get overall system health: disk, memory, docker, services",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Remote host address"},
                "user": {"type": "string", "description": "SSH user", "default": ""},
            },
            "required": ["host"],
        },
    },
    {
        "name": "ask_sysadmin",
        "description": "Delegate a task to the sysadmin agent for host-level operations",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "task": {"type": "string", "description": "sysadmin tool name (host_status, update_all, restart_service, disk_alert, top_processes)"},
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


def _deploy_service(args: dict) -> str:
    host = args.get("host", "")
    svc = args.get("service_name", "")
    image = args.get("image", "")
    user = args.get("user", "")
    lines = []
    if image:
        lines.append(f"Pulling {image}...")
        lines.append(_call("shell-mcp", "run_shell", {"host": host, "user": user, "command": f"docker pull {image} 2>&1"}))
    lines.append(f"Restarting {svc}...")
    lines.append(_call("shell-mcp", "run_shell", {"host": host, "user": user, "command": f"docker compose -p {svc} up -d 2>&1 || docker restart {svc} 2>&1"}))
    lines.append("")
    lines.append("=== Status ===")
    lines.append(_call("shell-mcp", "run_shell", {"host": host, "user": user, "command": f"docker ps --filter name={svc} --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>&1"}))
    return "\n".join(lines)


def _container_status(args: dict) -> str:
    host = args.get("host", "")
    user = args.get("user", "")
    return _call("shell-mcp", "run_shell", {"host": host, "user": user, "command": "docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1"})


def _logs_tail(args: dict) -> str:
    host = args.get("host", "")
    container = args.get("container", "")
    lines = args.get("lines", 50)
    user = args.get("user", "")
    return _call("shell-mcp", "run_shell", {"host": host, "user": user, "command": f"docker logs --tail {lines} {container} 2>&1"})


def _system_health(args: dict) -> str:
    host = args.get("host", "")
    user = args.get("user", "")
    lines = []
    lines.append("=== Disk Usage ===")
    lines.append(_call("shell-mcp", "run_shell", {"host": host, "user": user, "command": "df -h / 2>&1"}))
    lines.append("")
    lines.append("=== Memory ===")
    lines.append(_call("shell-mcp", "run_shell", {"host": host, "user": user, "command": "free -h 2>&1"}))
    lines.append("")
    lines.append("=== Docker ===")
    lines.append(_call("shell-mcp", "run_shell", {"host": host, "user": user, "command": "docker info --format '{{.ContainersRunning}} running / {{.Containers}} total' 2>&1 || echo 'Docker not available'"}))
    lines.append("")
    lines.append("=== Critical Services ===")
    lines.append(_call("shell-mcp", "run_shell", {"host": host, "user": user, "command": "systemctl is-active docker ssh nginx 2>&1"}))
    return "\n".join(lines)


def _ask_sysadmin(args: dict) -> str:
    agent = _get_agent()
    host_name = args.get("host_name", "")
    task = args.get("task", "")
    params = args.get("params", {})
    params["host_name"] = host_name
    return agent.ask_agent("sysadmin-agent", task, params)


TOOL_FUNCS = {
    "deploy_service": _deploy_service,
    "container_status": _container_status,
    "logs_tail": _logs_tail,
    "system_health": _system_health,
    "ask_sysadmin": _ask_sysadmin,
}

if __name__ == "__main__":
    port = int(os.getenv("DEVOPS_AGENT_PORT", "8011"))
    agent = BaseAgent(
        name="devops-agent",
        description="DevOps: deploy, containers, system health checks",
        tools=TOOLS,
        tool_funcs=TOOL_FUNCS,
        port=port,
        platform="local",
    )
    _agent_instance = agent
    agent.run()
