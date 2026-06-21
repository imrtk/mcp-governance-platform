"""vCenter Agent: VM management via vcenter-mcp."""
import os
from agents.base_agent import BaseAgent

MCP_NAME = "vcenter-mcp"

TOOLS = [
    {
        "name": "list_vms",
        "description": "List all VMs with power state, CPU, RAM, OS, IP",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "vm_status",
        "description": "Get detailed status of a specific VM",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "VM name"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "power_on",
        "description": "Power on a VM that is powered off",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "VM name"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "power_off",
        "description": "Gracefully shut down a VM",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "VM name"},
                "force": {"type": "boolean", "description": "Force power off", "default": False},
            },
            "required": ["name"],
        },
    },
    {
        "name": "reset_vm",
        "description": "Reset/reboot a VM",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "VM name"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "ensure_running",
        "description": "Check if a VM is running; if off, power it on",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "VM name"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "vm_info",
        "description": "Get comprehensive VM info (networks, disks, snapshots)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "VM name"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "cluster_resources",
        "description": "Get cluster resource usage (CPU, RAM, storage)",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "datastore_usage",
        "description": "List datastores with capacity and free space",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_snapshot",
        "description": "Create a snapshot of a VM",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "VM name"},
                "snapshot_name": {"type": "string", "description": "Snapshot name"},
                "description": {"type": "string", "description": "Snapshot description", "default": ""},
            },
            "required": ["name", "snapshot_name"],
        },
    },
    {
        "name": "deploy_vm",
        "description": "Deploy a new VM from a template",
        "inputSchema": {
            "type": "object",
            "properties": {
                "template_name": {"type": "string", "description": "Template name"},
                "vm_name": {"type": "string", "description": "New VM name"},
                "power_on": {"type": "boolean", "description": "Power on after deploy", "default": True},
            },
            "required": ["template_name", "vm_name"],
        },
    },
    {
        "name": "vm_summary",
        "description": "Get a human-readable summary of all VMs and cluster health",
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


def _list_vms(args: dict) -> str:
    return _call("list_vms", {})


def _vm_status(args: dict) -> str:
    name = args.get("name", "")
    return _call("vm_status", {"name": name})


def _power_on(args: dict) -> str:
    name = args.get("name", "")
    return _call("power_on", {"name": name})


def _power_off(args: dict) -> str:
    name = args.get("name", "")
    force = args.get("force", False)
    return _call("power_off", {"name": name, "force": force})


def _reset_vm(args: dict) -> str:
    name = args.get("name", "")
    return _call("reset_vm", {"name": name})


def _ensure_running(args: dict) -> str:
    name = args.get("name", "")
    status_raw = _call("vm_status", {"name": name})
    try:
        import json
        status = json.loads(status_raw)
        if status.get("power_state") == "poweredOn":
            return f"VM '{name}' is already running (IP: {status.get('ip', 'N/A')})"
    except Exception:
        pass
    return _call("power_on", {"name": name})


def _vm_info(args: dict) -> str:
    name = args.get("name", "")
    return _call("vm_info", {"name": name})


def _cluster_resources(args: dict) -> str:
    return _call("get_cluster_resources", {})


def _datastore_usage(args: dict) -> str:
    return _call("list_datastores", {})


def _create_snapshot(args: dict) -> str:
    name = args.get("name", "")
    snap_name = args.get("snapshot_name", "")
    description = args.get("description", "")
    return _call("create_snapshot", {"name": name, "snapshot_name": snap_name, "description": description})


def _deploy_vm(args: dict) -> str:
    template_name = args.get("template_name", "")
    vm_name = args.get("vm_name", "")
    power_on = args.get("power_on", True)
    return _call("deploy_from_template", {
        "template_name": template_name,
        "vm_name": vm_name,
        "power_on": power_on,
    })


def _vm_summary(args: dict) -> str:
    vms_raw = _call("list_vms", {})
    cluster_raw = _call("get_cluster_resources", {})
    return f"=== Cluster Resources ===\n\n{cluster_raw}\n\n=== VMs ===\n\n{vms_raw}"


TOOL_FUNCS = {
    "list_vms": _list_vms,
    "vm_status": _vm_status,
    "power_on": _power_on,
    "power_off": _power_off,
    "reset_vm": _reset_vm,
    "ensure_running": _ensure_running,
    "vm_info": _vm_info,
    "cluster_resources": _cluster_resources,
    "datastore_usage": _datastore_usage,
    "create_snapshot": _create_snapshot,
    "deploy_vm": _deploy_vm,
    "vm_summary": _vm_summary,
}

if __name__ == "__main__":
    port = int(os.getenv("VCENTER_AGENT_PORT", "8016"))
    agent = BaseAgent(
        name="vcenter-agent",
        description="vCenter VM management: list, power on/off, deploy, snapshots, resource monitoring",
        tools=TOOLS,
        tool_funcs=TOOL_FUNCS,
        port=port,
        platform="local",
    )
    _agent_instance = agent
    agent.run()
