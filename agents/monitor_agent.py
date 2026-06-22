import os, json, threading, time, datetime, httpx
from agents.base_agent import BaseAgent

LLM_API_URL = os.getenv("LLM_API_URL", "http://localhost:11434/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-coder:480b-cloud")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "60"))
MONITOR_IGNORE_TAG = os.getenv("MONITOR_IGNORE_TAG", "monitor-ignore")

_agent_instance = None
_alert_history: list[dict] = []
_alert_lock = threading.Lock()
_last_status = ""


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
    raw = _call_vcenter_agent("vcenter_list_vms", {"exclude_tag": MONITOR_IGNORE_TAG})
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
        "name": "status",
        "description": "Get latest monitoring status and alert history",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _check_vms(args: dict) -> str:
    global _last_status
    _last_status = _run_monitor_cycle()
    return _last_status


def _status(args: dict) -> str:
    global _last_status
    if not _last_status:
        _last_status = _run_monitor_cycle()
    return _last_status


TOOL_FUNCS = {
    "check_vms": _check_vms,
    "status": _status,
}


def _background_monitor():
    global _last_status
    while True:
        try:
            _last_status = _run_monitor_cycle()
            has_issue = "Kapali:" in _last_status and "0" not in _last_status.split("Kapali:")[1][:3]
            if has_issue:
                first_line = _last_status.split("\n")[0] if _last_status else ""
                print(f"[monitor-agent] {first_line}")
        except Exception as e:
            print(f"[monitor-agent] Monitor error: {e}")
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
