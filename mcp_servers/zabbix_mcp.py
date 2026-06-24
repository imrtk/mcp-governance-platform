import os, json, time, httpx
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from pydantic import BaseModel

ZABBIX_URL = os.environ.get("ZABBIX_URL", "")
ZABBIX_API_TOKEN = os.environ.get("ZABBIX_API_TOKEN", "")
ZABBIX_USER = os.environ.get("ZABBIX_USER", "Admin")
ZABBIX_PASSWORD = os.environ.get("ZABBIX_PASSWORD", "")

_auth_token = None


def _zapi(method: str, params: dict = None) -> dict:
    global _auth_token
    if not ZABBIX_URL:
        return {"error": "ZABBIX_URL environment variable not set"}
    api_url = ZABBIX_URL.rstrip("/") + "/api_jsonrpc.php"
    payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}
    if ZABBIX_API_TOKEN:
        payload["auth"] = ZABBIX_API_TOKEN
    elif _auth_token:
        payload["auth"] = _auth_token
    else:
        try:
            r = httpx.post(api_url, json={
                "jsonrpc": "2.0", "method": "user.login",
                "params": {"user": ZABBIX_USER, "password": ZABBIX_PASSWORD}, "id": 1,
            }, timeout=10)
            d = r.json()
            if "error" in d:
                return d
            _auth_token = d["result"]
            payload["auth"] = _auth_token
        except Exception as e:
            return {"error": f"Zabbix login failed: {e}"}
    try:
        r = httpx.post(api_url, json=payload, timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _result(data: dict) -> str:
    if "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({"result": data.get("result", [])}, indent=2)


TOOLS = [
    {
        "name": "zabbix_list_hosts",
        "description": "List all monitored hosts with status, IP, template info",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Filter by host name pattern", "default": ""},
                "status": {"type": "string", "description": "Filter: monitored, unmonitored, all", "default": "monitored"},
            },
        },
    },
    {
        "name": "zabbix_get_host",
        "description": "Get detailed host info including interfaces, groups, templates",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Host name or ID"},
            },
            "required": ["host"],
        },
    },
    {
        "name": "zabbix_list_alerts",
        "description": "Get recent triggered alerts/problems",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max alerts", "default": 50},
                "severity": {"type": "string", "description": "Filter: not_classified, information, warning, average, high, disaster", "default": ""},
                "acknowledged": {"type": "boolean", "description": "Filter by acknowledged state", "default": None},
            },
        },
    },
    {
        "name": "zabbix_get_metrics",
        "description": "Get metric/item values for a host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Host name or ID"},
                "item_key": {"type": "string", "description": "Item key filter (e.g. system.cpu.load, vm.memory.*)", "default": ""},
                "limit": {"type": "integer", "description": "Max items", "default": 20},
            },
            "required": ["host"],
        },
    },
    {
        "name": "zabbix_get_events",
        "description": "Get recent Zabbix events",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max events", "default": 50},
                "event_type": {"type": "string", "description": "trigger, discovery, etc.", "default": "trigger"},
                "severity": {"type": "string", "description": "Min severity filter", "default": ""},
            },
        },
    },
    {
        "name": "zabbix_create_host",
        "description": "Add a new host to Zabbix monitoring",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Host name"},
                "ip": {"type": "string", "description": "IP address"},
                "group_ids": {"type": "array", "description": "Host group IDs", "items": {"type": "string"}},
                "template_ids": {"type": "array", "description": "Template IDs to link", "items": {"type": "string"}},
                "proxy_id": {"type": "string", "description": "Proxy ID (optional)", "default": ""},
            },
            "required": ["host", "ip"],
        },
    },
    {
        "name": "zabbix_delete_host",
        "description": "Remove a host from Zabbix monitoring",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Host name or ID"},
            },
            "required": ["host"],
        },
    },
    {
        "name": "zabbix_acknowledge_event",
        "description": "Acknowledge a Zabbix event",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Event ID"},
                "message": {"type": "string", "description": "Acknowledge message", "default": "Acknowledged by MCP"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "zabbix_list_templates",
        "description": "List available Zabbix templates",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "zabbix_list_groups",
        "description": "List host groups",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "zabbix_get_dashboard",
        "description": "Get dashboard summary: host count, problem count, trigger stats",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _list_hosts(args: dict) -> str:
    pattern = args.get("pattern", "")
    status = args.get("status", "monitored")
    params = {
        "output": ["hostid", "host", "name", "status", "available"],
        "selectInterfaces": ["ip", "dns", "port", "type"],
        "selectGroups": ["groupid", "name"],
        "selectParentTemplates": ["templateid", "name"],
    }
    if pattern:
        params["search"] = {"host": pattern}
        params["searchByAny"] = True
    if status == "monitored":
        params["filter"] = {"status": 0}
    elif status == "unmonitored":
        params["filter"] = {"status": 1}
    data = _zapi("host.get", params)
    if "error" in data:
        return _result(data)
    hosts = data.get("result", [])
    lines = []
    for h in hosts:
        ip = (h.get("interfaces") or [{}])[0].get("ip", "N/A") if h.get("interfaces") else "N/A"
        st = "monitored" if h.get("status") == "0" else "unmonitored"
        av = {0: "unknown", 1: "available", 2: "unavailable"}.get(h.get("available"), "unknown")
        templates = ", ".join(t.get("name", "") for t in (h.get("parentTemplates") or []))
        lines.append(f"  {h['host']:25s} {st:12s} {av:12s} IP:{ip:15s} templates:[{templates}]")
    header = f"Hosts ({len(hosts)}):"
    return header + "\n" + "\n".join(lines) if lines else header + " (none)"


def _get_host(args: dict) -> str:
    host = args.get("host", "")
    data = _zapi("host.get", {
        "output": "extend",
        "selectInterfaces": "extend",
        "selectGroups": "extend",
        "selectParentTemplates": "extend",
        "selectInventory": "extend",
        "selectMacros": "extend",
        "search": {"host": host},
    })
    if "error" in data:
        return _result(data)
    hosts = data.get("result", [])
    if not hosts:
        data = _zapi("host.get", {
            "output": "extend",
            "hostids": host,
            "selectInterfaces": "extend",
            "selectGroups": "extend",
            "selectParentTemplates": "extend",
        })
        hosts = data.get("result", [])
    if not hosts:
        return json.dumps({"error": f"Host '{host}' not found"})
    return json.dumps(hosts[0], indent=2, default=str)


def _list_alerts(args: dict) -> str:
    limit = min(args.get("limit", 50), 200)
    severity = args.get("severity", "")
    ack = args.get("acknowledged")
    params = {
        "output": ["triggerid", "description", "priority", "status", "value", "lastchange"],
        "selectHosts": ["hostid", "host"],
        "selectLastEvent": ["eventid", "acknowledged", "clock", "severity"],
        "sortfield": "lastchange",
        "sortorder": "DESC",
        "filter": {"value": 1},
    }
    if severity:
        sev_map = {"not_classified": 0, "information": 1, "warning": 2, "average": 3, "high": 4, "disaster": 5}
        params["filter"]["priority"] = sev_map.get(severity.lower(), severity)
    data = _zapi("trigger.get", params)
    if "error" in data:
        return _result(data)
    triggers = data.get("result", [])[:limit]
    lines = []
    for t in triggers:
        hosts = ", ".join(h.get("host", "") for h in (t.get("hosts") or []))
        sev = {0: "NC", 1: "INFO", 2: "WARN", 3: "AVG", 4: "HIGH", 5: "DIS"}.get(t.get("priority"), "?")
        ev = t.get("lastEvent") or {}
        acked = "✓" if ev.get("acknowledged") == "1" else "✗"
        clock = ev.get("clock", "0")
        from_ts = str(datetime.fromtimestamp(int(clock)).strftime("%H:%M:%S")) if clock != "0" else ""
        lines.append(f"  [{sev}] {t['description'][:60]:60s} {hosts:20s} ack:{acked} {from_ts}")
    return f"Active triggers ({len(triggers)}):\n" + "\n".join(lines) if lines else "No active triggers"


def _get_metrics(args: dict) -> str:
    host_query = args.get("host", "")
    item_key = args.get("item_key", "")
    limit = min(args.get("limit", 20), 100)
    host_data = _zapi("host.get", {"output": ["hostid"], "search": {"host": host_query}})
    if "error" in host_data:
        return _result(host_data)
    hosts = host_data.get("result", [])
    if not hosts:
        host_data = _zapi("host.get", {"output": ["hostid"], "hostids": host_query})
        hosts = host_data.get("result", [])
    if not hosts:
        return json.dumps({"error": f"Host '{host_query}' not found"})
    host_id = hosts[0]["hostid"]
    params = {
        "output": ["itemid", "name", "key_", "lastvalue", "units", "value_type", "lastclock"],
        "hostids": host_id,
        "sortfield": "name",
        "sortorder": "ASC",
    }
    if item_key:
        params["search"] = {"key_": item_key}
        params["searchByAny"] = True
    data = _zapi("item.get", params)
    if "error" in data:
        return _result(data)
    items = data.get("result", [])[:limit]
    results = []
    for item in items:
        val = item.get("lastvalue", "N/A")
        unit = item.get("units", "")
        ts = item.get("lastclock", "0")
        from_ts = str(datetime.fromtimestamp(int(ts)).strftime("%H:%M:%S")) if ts != "0" else ""
        results.append({
            "name": item.get("name", ""),
            "key": item.get("key_", ""),
            "value": f"{val} {unit}".strip(),
            "time": from_ts,
        })
    return json.dumps({"host": host_query, "items": results}, indent=2)


def _get_events(args: dict) -> str:
    limit = min(args.get("limit", 50), 200)
    event_type = args.get("event_type", "trigger")
    severity = args.get("severity", "")
    params = {
        "output": ["eventid", "source", "object", "objectid", "clock", "acknowledged", "name", "severity"],
        "sortfield": "clock",
        "sortorder": "DESC",
        "selectHosts": ["host"],
        "select_alerts": ["alertid", "mediatypeid", "sendto", "subject", "status"],
    }
    if event_type == "trigger":
        params["source"] = 0
        params["object"] = 0
    if severity:
        sev_map = {"not_classified": 0, "information": 1, "warning": 2, "average": 3, "high": 4, "disaster": 5}
        params["severity"] = sev_map.get(severity.lower(), severity)
    data = _zapi("event.get", params)
    if "error" in data:
        return _result(data)
    events = data.get("result", [])[:limit]
    results = []
    for ev in events:
        clock = ev.get("clock", "0")
        ts = str(datetime.fromtimestamp(int(clock)).strftime("%Y-%m-%d %H:%M:%S")) if clock != "0" else ""
        results.append({
            "eventid": ev.get("eventid"),
            "time": ts,
            "name": ev.get("name", ""),
            "acknowledged": ev.get("acknowledged") == "1",
            "severity": ev.get("severity"),
        })
    return json.dumps({"event_count": len(results), "events": results}, indent=2)


def _create_host(args: dict) -> str:
    host = args.get("host", "")
    ip = args.get("ip", "")
    group_ids = args.get("group_ids", [])
    template_ids = args.get("template_ids", [])
    proxy_id = args.get("proxy_id", "")
    if not group_ids:
        data = _zapi("hostgroup.get", {"output": ["groupid"], "filter": {"name": "Discovered hosts"}})
        grps = data.get("result", [])
        if grps:
            group_ids = [grps[0]["groupid"]]
    interfaces = [{
        "type": 1, "main": 1, "useip": 1,
        "ip": ip, "dns": "", "port": "10050",
    }]
    params = {
        "host": host,
        "interfaces": interfaces,
        "groups": [{"groupid": g} for g in group_ids],
        "templates": [{"templateid": t} for t in template_ids],
    }
    if proxy_id:
        params["proxy_hostid"] = proxy_id
    data = _zapi("host.create", params)
    if "error" in data:
        return _result(data)
    host_ids = data.get("result", {}).get("hostids", [])
    return json.dumps({"status": "created", "host": host, "hostid": host_ids[0] if host_ids else None}, indent=2)


def _delete_host(args: dict) -> str:
    host_query = args.get("host", "")
    data = _zapi("host.get", {"output": ["hostid"], "search": {"host": host_query}})
    hosts = data.get("result", [])
    if not hosts:
        data = _zapi("host.get", {"output": ["hostid"], "hostids": host_query})
        hosts = data.get("result", [])
    if not hosts:
        return json.dumps({"error": f"Host '{host_query}' not found"})
    host_id = hosts[0]["hostid"]
    data = _zapi("host.delete", [host_id])
    if "error" in data:
        return _result(data)
    return json.dumps({"status": "deleted", "hostid": host_id})


def _acknowledge_event(args: dict) -> str:
    event_id = args.get("event_id", "")
    message = args.get("message", "Acknowledged by MCP")
    data = _zapi("event.acknowledge", {
        "eventids": event_id,
        "message": message,
        "action": 1,
    })
    if "error" in data:
        return _result(data)
    return json.dumps({"status": "acknowledged", "eventid": event_id})


def _list_templates(args: dict) -> str:
    data = _zapi("template.get", {
        "output": ["templateid", "host", "name", "description"],
        "sortfield": "host",
    })
    if "error" in data:
        return _result(data)
    templates = data.get("result", [])
    lines = [f"  {t['templateid']:10s} {t['host']:35s} {t.get('description', '')[:50]}" for t in templates]
    return f"Templates ({len(templates)}):\n" + "\n".join(lines) if lines else "No templates"


def _list_groups(args: dict) -> str:
    data = _zapi("hostgroup.get", {"output": ["groupid", "name"], "sortfield": "name"})
    if "error" in data:
        return _result(data)
    groups = data.get("result", [])
    lines = [f"  {g['groupid']:10s} {g['name']}" for g in groups]
    return f"Host groups ({len(groups)}):\n" + "\n".join(lines) if lines else "No groups"


def _get_dashboard(args: dict) -> str:
    hosts_data = _zapi("host.get", {"output": ["hostid", "status"], "countOutput": True, "group": ["hostid"]})
    hosts_count = _zapi("host.get", {"output": ["hostid"], "countOutput": True})
    problems_count = _zapi("trigger.get", {
        "output": ["triggerid"], "filter": {"value": 1},
        "countOutput": True, "skipDependent": True,
    })
    events_24h = _zapi("event.get", {
        "output": ["eventid"], "source": 0, "object": 0,
        "time_from": int(time.time() - 86400),
        "countOutput": True,
    })
    def _safe_count(data):
        return data.get("result", 0) if "error" not in data else 0
    return json.dumps({
        "total_hosts": _safe_count(hosts_count),
        "active_problems": _safe_count(problems_count),
        "events_last_24h": _safe_count(events_24h),
    }, indent=2)


TOOL_FUNCS = {
    "zabbix_list_hosts": _list_hosts,
    "zabbix_get_host": _get_host,
    "zabbix_list_alerts": _list_alerts,
    "zabbix_get_metrics": _get_metrics,
    "zabbix_get_events": _get_events,
    "zabbix_create_host": _create_host,
    "zabbix_delete_host": _delete_host,
    "zabbix_acknowledge_event": _acknowledge_event,
    "zabbix_list_templates": _list_templates,
    "zabbix_list_groups": _list_groups,
    "zabbix_get_dashboard": _get_dashboard,
}

app = FastAPI(title="zabbix-mcp")

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
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("ZABBIX_MCP_PORT", 8030)))
