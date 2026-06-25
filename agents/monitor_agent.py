import os, json, threading, time, datetime, httpx
from agents.base_agent import BaseAgent

LLM_API_URL = os.getenv("LLM_API_URL", "http://localhost:11434/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-coder:480b-cloud")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "60"))
RESOURCE_MONITOR_INTERVAL = int(os.getenv("RESOURCE_MONITOR_INTERVAL", "120"))
EVENT_MONITOR_INTERVAL = int(os.getenv("EVENT_MONITOR_INTERVAL", "300"))
ZABBIX_MONITOR_INTERVAL = int(os.getenv("ZABBIX_MONITOR_INTERVAL", "300"))
MONITOR_IGNORE_TAG = os.getenv("MONITOR_IGNORE_TAG", "monitor-ignore")
RESOURCE_CPU_THRESHOLD = float(os.getenv("RESOURCE_CPU_THRESHOLD", "85"))
RESOURCE_RAM_THRESHOLD = float(os.getenv("RESOURCE_RAM_THRESHOLD", "90"))
RESOURCE_DISK_THRESHOLD = float(os.getenv("RESOURCE_DISK_THRESHOLD", "85"))

_agent_instance = None
_alert_history: list[dict] = []
_alert_lock = threading.Lock()
_last_status = ""
_last_resource_status = ""
_last_event_status = ""
_last_zabbix_status = ""

PGSQL_AGENT_URL = os.getenv("PGSQL_AGENT_URL", "http://localhost:8021")


def _get_agent():
    global _agent_instance
    return _agent_instance


def _call_vcenter_agent(tool: str, params: dict) -> str:
    try:
        resp = httpx.post(
            f"{GATEWAY_URL}/api/gateway/agent/vcenter-agent/ask",
            json={"agent_id": "monitor-agent", "tool_name": tool, "params": params},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        contents = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in contents)
    except Exception as e:
        return f"[ERROR] {e}"


def _call_pgsql_agent(tool: str, params: dict) -> str:
    try:
        resp = httpx.post(
            f"{GATEWAY_URL}/api/gateway/agent/pgsql-agent/ask",
            json={"agent_id": "monitor-agent", "tool_name": tool, "params": params},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        contents = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in contents)
    except Exception as e:
        return f"[PGSQL-AGENT ERROR] {e}"


def _log_alert(source: str, level: str, host: str, service: str, message: str, action: str = "", result: str = ""):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    with _alert_lock:
        _alert_history.append({
            "time": ts, "host": host, "service": service,
            "action": action, "result": result[:120],
        })
    _call_pgsql_agent("pgsql_insert_alert", {
        "source": source, "level": level, "host": host,
        "service": service, "message": message,
        "action": action, "result": result[:200],
    })


def _insert_metric(source: str, metric: str, value: float, labels: dict | None = None):
    _call_pgsql_agent("pgsql_insert_metric", {
        "source": source,
        "metric": metric,
        "value": round(value, 2),
        "labels": labels or {},
    })


def _call_vcenter(tool: str, params: dict) -> str:
    try:
        resp = httpx.post(
            f"{GATEWAY_URL}/api/gateway/agent/vcenter-agent/ask",
            json={"agent_id": "monitor-agent", "tool_name": tool, "params": params},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        contents = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in contents)
    except Exception as e:
        return f"[VCENTER ERROR] {e}"


def _call_zabbix(tool: str, params: dict) -> str:
    try:
        resp = httpx.post(
            f"{GATEWAY_URL}/api/gateway/agent/zabbix-agent/ask",
            json={"agent_id": "monitor-agent", "tool_name": tool, "params": params},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        contents = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in contents)
    except Exception as e:
        return f"[ZABBIX ERROR] {e}"


def _check_resource_usage() -> str:
    cluster_raw = _call_vcenter("vcenter_cluster_resources", {})
    host_raw = _call_vcenter("vcenter_list_hosts", {})
    ds_raw = _call_vcenter("vcenter_list_datastores", {})
    alerts = []
    try:
        clusters = json.loads(cluster_raw)
        if isinstance(clusters, list):
            for c in clusters:
                name = c.get("name", "unknown")
                total_ram = c.get("total_ram_gb", 0)
                used_ram = c.get("used_ram_gb", 0)
                ram_pct = round(used_ram / total_ram * 100, 1) if total_ram > 0 else 0
                _insert_metric("monitor-agent", "cluster.ram.usage.percent", ram_pct, {"cluster": name})
                if ram_pct > RESOURCE_RAM_THRESHOLD:
                    msg = f"Cluster {name} RAM kullanimi {ram_pct}% (esik: {RESOURCE_RAM_THRESHOLD}%)"
                    _log_alert("monitor-agent", "warn", name, "cluster", msg)
                    alerts.append(msg)
    except Exception:
        pass
    try:
        for line in host_raw.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("Hosts"):
                continue
            parts = line.split()
            if len(parts) >= 5:
                host_name = parts[0]
                cpu_mhz = parts[3].replace("MHz", "") if len(parts) > 3 else "0"
                ram_gb = parts[4].replace("GB", "").replace("RAM", "") if len(parts) > 4 else "0"
                # hosts info shows total resources, no usage %
                _insert_metric("monitor-agent", "host.cpu.total.mhz", float(cpu_mhz or 0), {"host": host_name})
                _insert_metric("monitor-agent", "host.ram.total.gb", float(ram_gb or 0), {"host": host_name})
    except Exception:
        pass
    try:
        for line in ds_raw.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("Datastores"):
                continue
            parts = line.split()
            if len(parts) >= 7:
                ds_name = parts[0]
                used_pct_str = parts[-1].replace("%", "").replace("%used", "")
                try:
                    used_pct = float(used_pct_str)
                    _insert_metric("monitor-agent", "datastore.usage.percent", used_pct, {"datastore": ds_name})
                    if used_pct > RESOURCE_DISK_THRESHOLD:
                        msg = f"Datastore {ds_name} doluluk {used_pct}% (esik: {RESOURCE_DISK_THRESHOLD}%)"
                        _log_alert("monitor-agent", "warn", ds_name, "datastore", msg)
                        alerts.append(msg)
                except ValueError:
                    pass
    except Exception:
        pass
    if alerts:
        return f"[RESOURCE ALERTS]\n" + "\n".join(alerts)
    return "[RESOURCE] All resources within thresholds"


def _check_events_and_alarms() -> str:
    events_raw = _call_vcenter("vcenter_list_events", {"max_count": 50, "recent_minutes": 30})
    alarms_raw = _call_vcenter("vcenter_list_alarms", {})
    alerts = []
    try:
        ev_data = json.loads(events_raw)
        for ev in ev_data.get("events", []):
            etype = ev.get("type", "")
            severity = ev.get("severity", "info")
            msg_text = ev.get("message", "")
            vm = ev.get("vm", "")
            if "error" in etype.lower() or "error" in severity.lower() or "error" in msg_text.lower():
                _log_alert("monitor-agent", "error", vm or "vcenter", "event", msg_text[:200], action="auto-log")
                alerts.append(f"[EVENT ERROR] {vm}: {msg_text[:100]}")
            elif "warning" in severity.lower():
                _log_alert("monitor-agent", "warn", vm or "vcenter", "event", msg_text[:200], action="auto-log")
                alerts.append(f"[EVENT WARN] {vm}: {msg_text[:100]}")
    except Exception:
        pass
    try:
        alarm_data = json.loads(alarms_raw)
        for alarm in alarm_data.get("alarms", []):
            status = alarm.get("status", "").lower()
            vm = alarm.get("vm", "")
            alarm_name = alarm.get("alarm", "")
            if status == "red":
                _log_alert("monitor-agent", "error", vm, "alarm", f"Alarm: {alarm_name}", action="auto-log")
                alerts.append(f"[ALARM RED] {vm}: {alarm_name}")
            elif status == "yellow":
                _log_alert("monitor-agent", "warn", vm, "alarm", f"Alarm: {alarm_name}", action="auto-log")
                alerts.append(f"[ALARM YELLOW] {vm}: {alarm_name}")
    except Exception:
        pass
    if alerts:
        return "[EVENTS/ALARMS]\n" + "\n".join(alerts[:20])
    return "[EVENTS/ALARMS] No errors or triggered alarms in last 30 min"


def _check_zabbix_alerts() -> str:
    alerts_raw = _call_zabbix("zabbix_list_alerts", {"limit": 50})
    events_raw = _call_zabbix("zabbix_get_events", {"limit": 20, "severity": "average"})
    dashboard_raw = _call_zabbix("zabbix_get_dashboard", {})
    alerts = []
    try:
        if "Active triggers" in alerts_raw:
            for line in alerts_raw.strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("Active triggers"):
                    continue
                sev_map = {"NC": "info", "INFO": "info", "WARN": "warn", "AVG": "warn", "HIGH": "error", "DIS": "error"}
                sev_tag = line[2:5].strip() if len(line) > 5 else ""
                level = sev_map.get(sev_tag, "warn")
                desc = line[7:67].strip() if len(line) > 67 else line[7:].strip()
                host_part = line[68:88].strip() if len(line) > 88 else ""
                _log_alert("monitor-agent", level, host_part or "zabbix", "trigger", desc[:200], action="auto-log")
                alerts.append(f"[{sev_tag}] {host_part}: {desc[:80]}")
    except Exception as e:
        alerts.append(f"[ZABBIX PARSE ERROR] {e}")
    try:
        ev_data = json.loads(events_raw)
        for ev in ev_data.get("events", [])[:10]:
            name = ev.get("name", "")
            sev = int(ev.get("severity", 0))
            if sev >= 3:
                level = "error" if sev >= 4 else "warn"
                _log_alert("monitor-agent", level, "zabbix", "event", name[:200], action="auto-log")
                alerts.append(f"[EVENT] {name[:100]}")
    except Exception:
        pass
    try:
        dash = json.loads(dashboard_raw)
        problems = dash.get("active_problems", 0)
        events_24h = dash.get("events_last_24h", 0)
        _insert_metric("monitor-agent", "zabbix.active_problems", problems)
        _insert_metric("monitor-agent", "zabbix.events_24h", events_24h)
    except Exception:
        pass
    if alerts:
        return "[ZABBIX ALERTS]\n" + "\n".join(alerts[:20])
    return "[ZABBIX] No active problems"


def _ask_llm(prompt: str) -> str:
    try:
        headers = {"Content-Type": "application/json"}
        if LLM_API_KEY:
            headers["Authorization"] = f"Bearer {LLM_API_KEY}"
        payload = {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0.1,
        }
        resp = httpx.post(LLM_API_URL, json=payload, headers=headers, timeout=300)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f'{{"error": "LLM call failed: {e}"}}'


def _analyze_alerts(args: dict) -> str:
    alerts_raw = _call_zabbix("zabbix_list_alerts", {"limit": 1, "severity": "average"})
    events_raw = _call_zabbix("zabbix_get_events", {"limit": 1, "severity": "average"})

    prompt = f"""You are a Zabbix assistant. Analyze the latest alert/event.

Tools: zabbix_acknowledge_event(eventid,message), vcenter_ensure_running(name)

Alert: {alerts_raw[:600]}
Event: {events_raw[:600]}

JSON only:
{{"analysis":"turkce","severity":"low|medium|high|critical","suggested_tool":"tool or null","suggested_params":{{}},"explanation":"turkce"}}"""

    return _ask_llm(prompt)


def _call_orchestrator(task: str) -> str:
    try:
        resp = httpx.post(
            f"{GATEWAY_URL}/api/gateway/agent/orchestrator-agent/ask",
            json={"agent_id": "monitor-agent", "tool_name": "ask", "params": {"task": task}},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        contents = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in contents)
    except Exception as e:
        return f"[ORCHESTRATOR ERROR] {e}"


def _check_vcenter_vms() -> list[dict]:
    results = []
    raw = _call_vcenter_agent("vcenter_list_vms", {"exclude_tag": MONITOR_IGNORE_TAG, "exclude_templates": True})
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("VMs") or line.startswith("VCENTER_HOST") or line.startswith("No"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            vm_name = parts[0]
            vm_status = parts[1]
            vm_ip = parts[4] if len(parts) > 4 else "-"
            result = {"name": vm_name, "power_state": vm_status, "ip": vm_ip}
            if vm_status == "poweredOff":
                print(f"[monitor-agent] vCenter off: {vm_name}, orchestrator'a bildiriliyor...")
                fix_result = _call_orchestrator(f"{vm_name} VM'si kapali, vcenter_ensure_running ile ac. vcenter-agent kullan")
                result["auto_fix"] = fix_result
                result["fixed"] = True
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                with _alert_lock:
                    _alert_history.append({
                        "time": ts,
                        "host": f"vcenter:{vm_name}",
                        "service": "vm",
                        "action": "orchestrator",
                        "result": fix_result[:120],
                    })
                _call_pgsql_agent("pgsql_insert_alert", {
                    "source": "monitor-agent",
                    "level": "warn",
                    "host": vm_name,
                    "service": "vm",
                    "message": f"VM {vm_name} powered off, auto-fix triggered",
                    "action": "orchestrator",
                    "result": fix_result[:200],
                })
                print(f"[monitor-agent] ORCHESTRATOR {vm_name}: {fix_result[:60]}")
            else:
                result["fixed"] = False
            results.append(result)
    return results


def _run_monitor_cycle() -> str:
    vms = _check_vcenter_vms()
    total = len(vms)
    off = sum(1 for v in vms if v.get("fixed"))
    ok = total - off
    lines = [
        f"=== vCenter Monitor {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===",
        f"Toplam VM: {total} | Calisan: {ok} | Kapali: {off}",
    ]
    for vm in vms:
        icon = "✓" if not vm.get("fixed") else "🔧"
        lines.append(f"  {icon} {vm['name']}: {vm['power_state']}")
        if vm.get("fixed"):
            lines.append(f"      Auto-fix: {vm.get('auto_fix', '')[:80]}")
    with _alert_lock:
        if _alert_history:
            lines.append(f"\nSon mudahaleler ({len(_alert_history)}):")
            for a in _alert_history[-5:]:
                status = "✓" if "OK" in a["result"] else "✗"
                lines.append(f"  {status} {a['time']} {a['host']}/{a['service']} -> {a['result'][:50]}")
    return "\n".join(lines)


TOOLS = [
    {
        "name": "check_vms",
        "description": "Check all vCenter VMs, report powered-off VMs, trigger auto-fix",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_resources",
        "description": "Check cluster/host/datastore resource usage, store metrics, alert on thresholds",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_events",
        "description": "Check recent vCenter events and triggered alarms, log errors/warnings",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_zabbix",
        "description": "Check Zabbix alerts/events/dashboard, log problems to database",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "status",
        "description": "Get latest monitoring status and alert history",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "analyze_alerts",
        "description": "Analyze Zabbix alerts with LLM, get suggested actions and tool recommendations",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _check_vms(args: dict) -> str:
    global _last_status
    _last_status = _run_monitor_cycle()
    return _last_status


def _check_resources(args: dict) -> str:
    global _last_resource_status
    _last_resource_status = _check_resource_usage()
    return _last_resource_status


def _check_events(args: dict) -> str:
    global _last_event_status
    _last_event_status = _check_events_and_alarms()
    return _last_event_status


def _check_zabbix(args: dict) -> str:
    global _last_zabbix_status
    _last_zabbix_status = _check_zabbix_alerts()
    return _last_zabbix_status


def _status(args: dict) -> str:
    global _last_status
    if not _last_status:
        _last_status = _run_monitor_cycle()
    parts = [_last_status]
    if _last_resource_status:
        parts.append(f"\n=== Resource Monitoring ===\n{_last_resource_status}")
    if _last_event_status:
        parts.append(f"\n=== Event/Alarm Monitoring ===\n{_last_event_status}")
    if _last_zabbix_status:
        parts.append(f"\n=== Zabbix Monitoring ===\n{_last_zabbix_status}")
    with _alert_lock:
        if _alert_history:
            parts.append(f"\n=== Alert History ({len(_alert_history)} total) ===")
            for a in _alert_history[-10:]:
                icon = "✓" if "OK" in a["result"] else "✗"
                parts.append(f"  {icon} {a['time']} {a['host']}/{a['service']} -> {a['result'][:50]}")
    return "\n".join(parts)


TOOL_FUNCS = {
    "check_vms": _check_vms,
    "check_resources": _check_resources,
    "check_events": _check_events,
    "check_zabbix": _check_zabbix,
    "status": _status,
    "analyze_alerts": _analyze_alerts,
}


def _background_monitor():
    global _last_status, _last_resource_status, _last_event_status, _last_zabbix_status
    resource_counter = 0
    event_counter = 0
    zabbix_counter = 0
    while True:
        try:
            _last_status = _run_monitor_cycle()
            has_issue = "Kapali:" in _last_status and "0" not in _last_status.split("Kapali:")[1][:3]
            if has_issue:
                first_line = _last_status.split("\n")[0] if _last_status else ""
                print(f"[monitor-agent] VM Monitor: {first_line}")
        except Exception as e:
            print(f"[monitor-agent] VM Monitor error: {e}")

        resource_counter += MONITOR_INTERVAL
        if resource_counter >= RESOURCE_MONITOR_INTERVAL:
            resource_counter = 0
            try:
                _last_resource_status = _check_resource_usage()
                first_line = _last_resource_status.split("\n")[0] if _last_resource_status else ""
                print(f"[monitor-agent] Resource: {first_line}")
            except Exception as e:
                print(f"[monitor-agent] Resource error: {e}")

        event_counter += MONITOR_INTERVAL
        if event_counter >= EVENT_MONITOR_INTERVAL:
            event_counter = 0
            try:
                _last_event_status = _check_events_and_alarms()
                first_line = _last_event_status.split("\n")[0] if _last_event_status else ""
                print(f"[monitor-agent] Event: {first_line}")
            except Exception as e:
                print(f"[monitor-agent] Event error: {e}")

        zabbix_counter += MONITOR_INTERVAL
        if zabbix_counter >= ZABBIX_MONITOR_INTERVAL:
            zabbix_counter = 0
            try:
                _last_zabbix_status = _check_zabbix_alerts()
                first_line = _last_zabbix_status.split("\n")[0] if _last_zabbix_status else ""
                print(f"[monitor-agent] Zabbix: {first_line}")
            except Exception as e:
                print(f"[monitor-agent] Zabbix error: {e}")

        time.sleep(MONITOR_INTERVAL)


if __name__ == "__main__":
    port = int(os.getenv("MONITOR_AGENT_PORT", "8014"))
    agent = BaseAgent(
        name="monitor-agent",
        description="vCenter VM monitor: checks powered-off VMs and triggers auto-fix via orchestrator",
        tools=TOOLS,
        tool_funcs=TOOL_FUNCS,
        port=port,
        platform="local",
    )
    _agent_instance = agent
    t = threading.Thread(target=_background_monitor, daemon=True)
    t.start()
    agent.run()
