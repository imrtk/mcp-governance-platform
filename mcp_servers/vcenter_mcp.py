import os, json, ssl, time, re, httpx
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from pydantic import BaseModel

VCENTER_HOST = os.environ.get("VCENTER_HOST", "")
VCENTER_USER = os.environ.get("VCENTER_USER", "")
VCENTER_PASSWORD = os.environ.get("VCENTER_PASSWORD", "")
VCENTER_PORT = int(os.environ.get("VCENTER_PORT", "443"))
VCENTER_DATACENTER = os.environ.get("VCENTER_DATACENTER", "")
SSL_VERIFY = os.environ.get("VCENTER_SSL_VERIFY", "false").lower() == "true"

_si = None


def _connect():
    global _si
    if _si:
        try:
            _si.CurrentTime()
            return _si
        except Exception:
            _si = None
    try:
        from pyVmomi import vim
        from pyVim.connect import SmartConnect, Disconnect
    except ImportError:
        raise ImportError("pyVmomi required: pip install pyvmomi")

    ctx = ssl._create_unverified_context() if not SSL_VERIFY else None
    _si = SmartConnect(
        host=VCENTER_HOST,
        user=VCENTER_USER,
        pwd=VCENTER_PASSWORD,
        port=VCENTER_PORT,
        sslContext=ctx,
    )
    return _si


def _disconnect():
    global _si
    if _si:
        try:
            from pyVim.connect import Disconnect
            Disconnect(_si)
        except Exception:
            pass
        _si = None


def _get_content():
    si = _connect()
    return si.RetrieveContent()


def _get_datacenter(content):
    if VCENTER_DATACENTER:
        for dc in content.rootFolder.childEntity:
            if dc.name == VCENTER_DATACENTER:
                return dc
        return None
    for dc in content.rootFolder.childEntity:
        return dc
    return None


def _walk_vms(dc):
    vms = []
    for folder in [dc.vmFolder]:
        _walk_folder(folder, vms)
    return vms


def _walk_folder(folder, vms):
    for child in folder.childEntity:
        if hasattr(child, 'childEntity'):
            _walk_folder(child, vms)
        elif hasattr(child, 'name'):
            vms.append(child)


def _find_vm(name):
    content = _get_content()
    dc = _get_datacenter(content)
    if not dc:
        return None
    for vm in _walk_vms(dc):
        if vm.name.lower() == name.lower():
            return vm
    return None


def _vm_summary(vm):
    try:
        summary = vm.summary
        guest = summary.config.guestFullName or "N/A"
        power = summary.runtime.powerState
        cpu = summary.config.numCpu or 0
        ram_mb = summary.config.memorySizeMB or 0
        ip = str(summary.guest.ipAddress) if summary.guest and summary.guest.ipAddress else "N/A"
        return {
            "name": vm.name,
            "power_state": str(power) if power else "unknown",
            "cpu": cpu,
            "ram_mb": ram_mb,
            "os": guest,
            "ip": ip,
        }
    except Exception as e:
        return {"name": getattr(vm, 'name', 'unknown'), "error": str(e)}


TOOLS = [
    {
        "name": "vcenter_list_vms",
        "description": "List all VMs in the datacenter with power state, CPU, RAM, OS",
        "inputSchema": {
            "type": "object",
            "properties": {
                "exclude_tag": {"type": "string", "description": "Optional tag name; VMs with this tag are excluded from results"},
                "exclude_templates": {"type": "boolean", "description": "Exclude template VMs from results", "default": False},
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
        "description": "Gracefully shut down a VM (guest OS shutdown)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "VM name"},
                "force": {"type": "boolean", "description": "Force power off if guest tools unavailable", "default": False},
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
        "name": "vcenter_vm_info",
        "description": "Get comprehensive info about a VM including networks, disks, snapshots",
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
        "description": "Get cluster resource usage summary (CPU, memory, storage)",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "vcenter_list_datastores",
        "description": "List all datastores with capacity and free space",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "vcenter_list_hosts",
        "description": "List ESXi hosts with connection state and resource usage",
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
                "memory": {"type": "boolean", "description": "Include VM memory in snapshot", "default": False},
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
                "datastore": {"type": "string", "description": "Target datastore name (optional)"},
                "cluster": {"type": "string", "description": "Target cluster name (optional)"},
                "power_on": {"type": "boolean", "description": "Power on after deploy", "default": True},
            },
            "required": ["template_name", "vm_name"],
        },
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


def _vm_has_tag(vm, tag_name: str) -> bool:
    annotation = getattr(vm.summary.config, 'annotation', None) or ''
    if tag_name.lower() in re.split(r'[\s,;]+', annotation.lower()):
        return True
    try:
        content = _get_content()
        if hasattr(content, 'taggingManager') and content.taggingManager:
            tagging = content.taggingManager

            # Approach 1: ListTagsForObject — returns tag names (str) or tag objects
            try:
                tags = tagging.ListTagsForObject(vm)
                if tags:
                    if isinstance(tags[0], str):
                        if any(t.lower() == tag_name.lower() for t in tags):
                            return True
                    else:
                        if any(t.name.lower() == tag_name.lower() for t in tags):
                            return True
            except Exception:
                pass

            # Approach 2: ListAllTags + ListAttachedObjects
            try:
                all_tags = tagging.ListAllTags()
                target = next((t for t in all_tags if t.name.lower() == tag_name.lower()), None)
                if target:
                    objs = tagging.ListAttachedObjects(target.id)
                    if any(o.id == vm._moId and o.type == 'VirtualMachine' for o in objs):
                        return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _get_tagged_vms(tag_name: str) -> set:
    """Get set of VM moId values that have a given vCenter tag via REST API.
    Supports both /api/ (vCenter 7+) and /rest/ (vCenter 6.5/6.7) endpoints."""
    if not VCENTER_HOST:
        return set()
    for api_prefix in ("/api", "/rest/com/vmware"):
        try:
            base = f"https://{VCENTER_HOST}:{VCENTER_PORT}"
            with httpx.Client(verify=SSL_VERIFY, timeout=15) as client:
                if api_prefix == "/api":
                    r = client.post(f"{base}/api/session", auth=(VCENTER_USER, VCENTER_PASSWORD),
                                   headers={"Content-Type": "application/json"})
                    if r.status_code != 201:
                        continue
                    token = r.json()
                else:
                    r = client.post(f"{base}/rest/com/vmware/cis/session", auth=(VCENTER_USER, VCENTER_PASSWORD),
                                   headers={"Content-Type": "application/json"})
                    if r.status_code != 200:
                        continue
                    token = r.json().get("value", "")

                headers = {"vmware-api-session-id": token, "Content-Type": "application/json"}

                r = client.get(f"{base}{api_prefix}/cis/tagging/tag", headers=headers)
                if r.status_code != 200:
                    continue
                tags = r.json() if api_prefix == "/api" else r.json().get("value", [])
                tag_id = None
                for t in tags:
                    if t.get("name", "").lower() == tag_name.lower():
                        tag_id = t.get("id")
                        break
                if not tag_id:
                    return set()

                if api_prefix == "/api":
                    r = client.post(f"{base}/api/cis/tagging/tag-association?~action=list-attached-objects",
                                  json={"tag_id": tag_id}, headers=headers)
                    if r.status_code != 200:
                        continue
                    objs = r.json()
                else:
                    r = client.post(f"{base}/rest/com/vmware/cis/tagging/tag-association?id={tag_id}&~action=list-attached-objects",
                                  headers=headers)
                    if r.status_code != 200:
                        continue
                    objs = r.json().get("value", [])
                return {o["id"] for o in objs if o.get("type") == "VirtualMachine"}
        except Exception:
            continue
    return set()


def _list_vms(args: dict) -> str:
    exclude_tag = args.get("exclude_tag", "")
    exclude_templates = args.get("exclude_templates", False)
    if not VCENTER_HOST:
        return "VCENTER_HOST environment variable not set"
    content = _get_content()
    dc = _get_datacenter(content)
    if not dc:
        return "No datacenter found"
    vms = _walk_vms(dc)
    if not vms:
        return "No VMs found in datacenter"

    tagging_available = hasattr(content, 'taggingManager') and bool(content.taggingManager)
    exclude_mo_ids = _get_tagged_vms(exclude_tag) if exclude_tag and not tagging_available else set()

    lines = []
    for vm in sorted(vms, key=lambda v: v.name.lower()):
        if exclude_tag:
            if tagging_available:
                if _vm_has_tag(vm, exclude_tag):
                    continue
            elif vm._moId in exclude_mo_ids or _vm_has_tag(vm, exclude_tag):
                continue
        is_template = getattr(vm.summary.config, 'template', False)
        if exclude_templates and is_template:
            continue
        s = _vm_summary(vm)
        if "error" in s:
            lines.append(f"  {s['name']:25s} ERROR: {s['error']}")
        else:
            t = " [TEMPLATE]" if is_template and not exclude_templates else ""
            lines.append(f"  {s['name']:25s} {s['power_state']:12s} {s['cpu']}cpu {s['ram_mb']}MB {s['ip']:15s} {s['os'][:40]}{t}")
    return f"VMs ({len(lines)}):\n" + "\n".join(lines)


def _vm_status(args: dict) -> str:
    name = args.get("name", "")
    vm = _find_vm(name)
    if not vm:
        return f"VM '{name}' not found"
    s = _vm_summary(vm)
    return json.dumps(s, indent=2)


def _power_on(args: dict) -> str:
    name = args.get("name", "")
    vm = _find_vm(name)
    if not vm:
        return f"VM '{name}' not found"
    if vm.runtime.powerState == "poweredOn":
        return f"VM '{name}' is already powered on"
    try:
        task = vm.PowerOn()
        _wait_task(task)
        return f"VM '{name}' powered on successfully"
    except Exception as e:
        return f"Failed to power on '{name}': {e}"


def _power_off(args: dict) -> str:
    name = args.get("name", "")
    force = args.get("force", False)
    vm = _find_vm(name)
    if not vm:
        return f"VM '{name}' not found"
    if vm.runtime.powerState == "poweredOff":
        return f"VM '{name}' is already powered off"
    try:
        if force:
            task = vm.PowerOff()
            _wait_task(task)
            return f"VM '{name}' force powered off"
        else:
            vm.ShutdownGuest()
            return f"Guest shutdown requested for '{name}'"
    except Exception as e:
        return f"Failed to power off '{name}': {e}"


def _reset_vm(args: dict) -> str:
    name = args.get("name", "")
    vm = _find_vm(name)
    if not vm:
        return f"VM '{name}' not found"
    if vm.runtime.powerState != "poweredOn":
        return f"VM '{name}' is not powered on"
    try:
        task = vm.ResetVM_Task()
        _wait_task(task)
        return f"VM '{name}' reset successfully"
    except Exception as e:
        return f"Failed to reset '{name}': {e}"


def _vm_info(args: dict) -> str:
    name = args.get("name", "")
    vm = _find_vm(name)
    if not vm:
        return f"VM '{name}' not found"
    info = _vm_summary(vm)
    info["networks"] = []
    if vm.guest and vm.guest.net:
        for net in vm.guest.net:
            info["networks"].append({
                "name": net.network,
                "ip": net.ipAddress[0] if net.ipAddress else "N/A",
                "mac": net.macAddress,
            })
    info["disks"] = []
    if vm.config and vm.config.hardware and vm.config.hardware.device:
        for dev in vm.config.hardware.device:
            if hasattr(dev, 'capacityInKB'):
                gb = dev.capacityInKB / 1024 / 1024
                label = getattr(dev, 'deviceInfo', None)
                label = label.label if label else "disk"
                info["disks"].append({"label": label, "size_gb": round(gb, 1)})
    info["snapshots"] = []
    if vm.snapshot:
        _walk_snap(vm.snapshot.rootSnapshotList, info["snapshots"])
    return json.dumps(info, indent=2)


def _walk_snap(snap_list, result):
    for snap in snap_list:
        result.append({
            "name": snap.name,
            "description": snap.description or "",
            "created": str(snap.createTime),
            "state": str(snap.state),
        })
        if snap.childSnapshotList:
            _walk_snap(snap.childSnapshotList, result)


def _get_cluster_resources(args: dict) -> str:
    content = _get_content()
    dc = _get_datacenter(content)
    if not dc:
        return "No datacenter found"
    clusters = []
    for folder in dc.hostFolder.childEntity:
        if hasattr(folder, 'childEntity'):
            for c in folder.childEntity:
                if hasattr(c, 'resourcePool'):
                    clusters.append(c)
        elif hasattr(folder, 'resourcePool'):
            clusters.append(folder)
    if not clusters:
        return "No clusters found"
    results = []
    for cluster in clusters:
        total_cpu = sum(h.hardware.cpuInfo.hz for h in cluster.host) if cluster.host else 0
        total_ram = sum(h.hardware.memorySize for h in cluster.host) if cluster.host else 0
        used_cpu = 0
        used_ram = 0
        for host in cluster.host:
            for vm in host.vm:
                if vm.runtime.powerState == "poweredOn":
                    used_cpu += vm.summary.config.numCpu or 0
                    used_ram += vm.summary.config.memorySizeMB or 0
        total_ram_gb = total_ram / 1024 / 1024 / 1024
        results.append({
            "name": cluster.name,
            "host_count": len(cluster.host) if cluster.host else 0,
            "cpu_mhz_per_core": round(total_cpu / 1000000, 1) if total_cpu else 0,
            "total_ram_gb": round(total_ram_gb, 1),
            "used_ram_gb": round(used_ram / 1024, 1),
            "used_vcpu": used_cpu,
        })
    return json.dumps(results, indent=2)


def _list_datastores(args: dict) -> str:
    content = _get_content()
    dc = _get_datacenter(content)
    if not dc:
        return "No datacenter found"
    stores = dc.datastoreFolder.childEntity if hasattr(dc, 'datastoreFolder') else []
    if not stores:
        stores = content.rootFolder.childEntity[0].datastore
    if not stores:
        return "No datastores found"
    lines = []
    for ds in stores:
        cap = ds.summary.capacity if ds.summary.capacity else 0
        free = ds.summary.freeSpace if ds.summary.freeSpace else 0
        used_pct = round((1 - free / cap) * 100, 1) if cap > 0 else 0
        lines.append(f"  {ds.name:25s} {ds.summary.type or 'N/A':8s} {round(cap/1024**4, 1):>6.1f}TB total  {round(free/1024**4, 1):>6.1f}TB free  {used_pct}% used")
    return "Datastores:\n" + "\n".join(lines) if lines else "No datastores found"


def _list_hosts(args: dict) -> str:
    content = _get_content()
    dc = _get_datacenter(content)
    if not dc:
        return "No datacenter found"
    hosts = []
    for folder in dc.hostFolder.childEntity:
        if hasattr(folder, 'childEntity'):
            for c in folder.childEntity:
                if hasattr(c, 'host'):
                    for h in c.host:
                        hosts.append(h)
        elif hasattr(folder, 'host'):
            for h in folder.host:
                hosts.append(h)
    if not hosts:
        return "No hosts found"
    lines = []
    for host in hosts:
        cpu = host.hardware.cpuInfo.hz / 1000000 if host.hardware.cpuInfo else 0
        ram = host.hardware.memorySize / 1024 / 1024 / 1024 if host.hardware.memorySize else 0
        lines.append(f"  {host.name:25s} {str(host.runtime.connectionState):12s} {round(cpu, 0):>6.0f}MHz {round(ram, 1):>5.1f}GB RAM")
    return "Hosts:\n" + "\n".join(lines)


def _create_snapshot(args: dict) -> str:
    name = args.get("name", "")
    snap_name = args.get("snapshot_name", "")
    description = args.get("description", "")
    memory = args.get("memory", False)
    vm = _find_vm(name)
    if not vm:
        return f"VM '{name}' not found"
    try:
        task = vm.CreateSnapshot(snap_name, description, memory, False)
        _wait_task(task)
        return f"Snapshot '{snap_name}' created for '{name}'"
    except Exception as e:
        return f"Failed to create snapshot: {e}"


def _deploy_from_template(args: dict) -> str:
    from pyVmomi import vim
    template_name = args.get("template_name", "")
    vm_name = args.get("vm_name", "")
    datastore_name = args.get("datastore", "")
    cluster_name = args.get("cluster", "")
    power_on = args.get("power_on", True)

    content = _get_content()
    dc = _get_datacenter(content)
    if not dc:
        return "No datacenter found"

    template = _find_vm(template_name)
    if not template:
        return f"Template '{template_name}' not found"
    if not template.config.template:
        return f"'{template_name}' is not a template"

    pool = None
    datastore = None
    folder = dc.vmFolder

    if cluster_name:
        for folder_entry in dc.hostFolder.childEntity:
            if hasattr(folder_entry, 'childEntity'):
                for c in folder_entry.childEntity:
                    if hasattr(c, 'resourcePool') and c.name.lower() == cluster_name.lower():
                        pool = c.resourcePool
                        break
            elif hasattr(folder_entry, 'resourcePool') and folder_entry.name.lower() == cluster_name.lower():
                pool = folder_entry.resourcePool
    if not pool:
        pool = dc.hostFolder.childEntity[0].resourcePool

    if datastore_name:
        for ds in dc.datastore:
            if ds.name.lower() == datastore_name.lower():
                datastore = ds
                break

    clone_spec = vim.vm.CloneSpec(
        powerOn=power_on,
        template=False,
        location=vim.vm.RelocateSpec(
            pool=pool,
            datastore=datastore,
        ),
    )
    try:
        task = template.Clone(folder, vm_name, clone_spec)
        _wait_task(task, timeout=600)
        return f"VM '{vm_name}' deployed from template '{template_name}'"
    except Exception as e:
        return f"Failed to deploy VM: {e}"


def _vm_has_tag_tool(args: dict) -> str:
    name = args.get("name", "")
    tag_name = args.get("tag_name", "")
    vm = _find_vm(name)
    if not vm:
        return json.dumps({"vm": name, "has_tag": False, "error": "VM not found"})
    annotation = getattr(vm.summary.config, 'annotation', None) or ''
    try:
        content = _get_content()
        tagging_available = hasattr(content, 'taggingManager') and bool(content.taggingManager)
    except:
        tagging_available = False
    result = {
        "vm": name,
        "tag_name": tag_name,
        "has_tag": _vm_has_tag(vm, tag_name),
        "annotation": annotation,
        "tagging_api_available": tagging_available,
    }
    return json.dumps(result, indent=2)


def _wait_task(task, timeout=300):
    start = time.time()
    while True:
        if time.time() - start > timeout:
            raise TimeoutError("Task timed out")
        if task.info.state == "success":
            return
        elif task.info.state == "error":
            raise Exception(task.info.error.msg if hasattr(task.info, 'error') and task.info.error else "Task failed")
        time.sleep(2)


TOOL_FUNCS = {
    "vcenter_list_vms": _list_vms,
    "vcenter_vm_status": _vm_status,
    "vcenter_power_on": _power_on,
    "vcenter_power_off": _power_off,
    "vcenter_reset_vm": _reset_vm,
    "vcenter_vm_info": _vm_info,
    "vcenter_cluster_resources": _get_cluster_resources,
    "vcenter_list_datastores": _list_datastores,
    "vcenter_list_hosts": _list_hosts,
    "vcenter_create_snapshot": _create_snapshot,
    "vcenter_deploy_vm": _deploy_from_template,
    "vcenter_vm_has_tag": _vm_has_tag_tool,
}

app = FastAPI(title="vcenter-mcp")

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
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MCP_PORT", 8006)))
