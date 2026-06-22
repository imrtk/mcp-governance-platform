"""vCenter Agent: VM management via vcenter-mcp."""
import os
from agents.base_agent import BaseAgent

MCP_NAME = "vcenter-mcp"

TOOLS = [
    {
        "name": "vcenter_list_vms",
        "description": "List all VMs with power state, CPU, RAM, OS, IP",
        "inputSchema": {
            "type": "object",
            "properties": {
                "exclude_tag": {"type": "string", "description": "Optional tag name; VMs with this tag are excluded"},
            },
        },
    },
    {
        "name": "vcenter_vm_status",
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
        "name": "vcenter_power_on",
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
        "name": "vcenter_power_off",
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
        "name": "vcenter_reset_vm",
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
        "name": "vcenter_ensure_running",
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
        "name": "vcenter_vm_info",
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
        "name": "vcenter_cluster_resources",
        "description": "Get cluster resource usage (CPU, RAM, storage)",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "vcenter_list_hosts",
        "description": "List ESXi hosts with connection state and resource usage",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "vcenter_datastore_usage",
        "description": "List datastores with capacity and free space",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "vcenter_create_snapshot",
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
        "name": "vcenter_deploy_vm",
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
        "name": "vcenter_vm_summary",
        "description": "Get a human-readable summary of all VMs and cluster health",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "vcenter_vm_has_tag",
        "description": "Check if a VM has a specific tag (checks annotation first, then vCenter tagging API)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "VM name"},
                "tag_name": {"type": "string", "description": "Tag name to check"},
            },
            "required": ["name", "tag_name"],
        },
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
    exclude_tag = args.get("exclude_tag", "")
    exclude_templates = args.get("exclude_templates", False)
    return _call("vcenter_list_vms", {"exclude_tag": exclude_tag, "exclude_templates": exclude_templates})


def _vm_status(args: dict) -> str:
    name = args.get("name", "")
    return _call("vcenter_vm_status", {"name": name})


def _power_on(args: dict) -> str:
    name = args.get("name", "")
    return _call("vcenter_power_on", {"name": name})


def _power_off(args: dict) -> str:
    name = args.get("name", "")
    force = args.get("force", False)
    return _call("vcenter_power_off", {"name": name, "force": force})


def _reset_vm(args: dict) -> str:
    name = args.get("name", "")
    return _call("vcenter_reset_vm", {"name": name})


def _ensure_running(args: dict) -> str:
    name = args.get("name", "")
    status_raw = _call("vcenter_vm_status", {"name": name})
    try:
        import json
        status = json.loads(status_raw)
        if status.get("power_state") == "poweredOn":
            return f"VM '{name}' is already running (IP: {status.get('ip', 'N/A')})"
    except Exception:
        pass
    return _call("vcenter_power_on", {"name": name})


def _vm_info(args: dict) -> str:
    name = args.get("name", "")
    return _call("vcenter_vm_info", {"name": name})


def _cluster_resources(args: dict) -> str:
    return _call("vcenter_cluster_resources", {})


def _datastore_usage(args: dict) -> str:
    return _call("vcenter_list_datastores", {})


def _create_snapshot(args: dict) -> str:
    name = args.get("name", "")
    snap_name = args.get("snapshot_name", "")
    description = args.get("description", "")
    return _call("vcenter_create_snapshot", {"name": name, "snapshot_name": snap_name, "description": description})


def _deploy_vm(args: dict) -> str:
    template_name = args.get("template_name", "")
    vm_name = args.get("vm_name", "")
    power_on = args.get("power_on", True)
    return _call("vcenter_deploy_vm", {
        "template_name": template_name,
        "vm_name": vm_name,
        "power_on": power_on,
    })


def _list_hosts(args: dict) -> str:
    return _call("vcenter_list_hosts", {})


def _vm_summary(args: dict) -> str:
    vms_raw = _call("vcenter_list_vms", {})
    cluster_raw = _call("vcenter_cluster_resources", {})
    return f"=== Cluster Resources ===\n\n{cluster_raw}\n\n=== VMs ===\n\n{vms_raw}"


def _vm_has_tag(args: dict) -> str:
    name = args.get("name", "")
    tag_name = args.get("tag_name", "")
    return _call("vcenter_vm_has_tag", {"name": name, "tag_name": tag_name})


TOOL_FUNCS = {
    "vcenter_list_vms": _list_vms,
    "vcenter_vm_status": _vm_status,
    "vcenter_power_on": _power_on,
    "vcenter_power_off": _power_off,
    "vcenter_reset_vm": _reset_vm,
    "vcenter_ensure_running": _ensure_running,
    "vcenter_vm_info": _vm_info,
    "vcenter_cluster_resources": _cluster_resources,
    "vcenter_list_hosts": _list_hosts,
    "vcenter_datastore_usage": _datastore_usage,
    "vcenter_create_snapshot": _create_snapshot,
    "vcenter_deploy_vm": _deploy_vm,
    "vcenter_vm_summary": _vm_summary,
    "vcenter_vm_has_tag": _vm_has_tag,
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
