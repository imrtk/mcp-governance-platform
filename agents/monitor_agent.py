import os, json, threading, time, datetime, httpx
from agents.base_agent import BaseAgent

DEBIAN_MCP_URL = os.getenv("DEBIAN_MCP_URL", "http://localhost:8003")
DO_MCP_URL = os.getenv("DO_MCP_URL", "http://localhost:8005/mcp")
LLM_API_URL = os.getenv("LLM_API_URL", "http://localhost:11434/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-coder:480b-cloud")


def _llm_analyze(host: str, svc: str, logs: str) -> str:
    prompt = f"""Host: {host}
Service: {svc} is DOWN (not running).

Recent journalctl logs:
{logs[:2000]}

Analyze the logs and decide: should this service be restarted?
Reply with ONLY one word: YES or NO and a one-line reason.
Example: YES - service exited cleanly, no config errors
Example: NO - configuration error detected in logs"""
    try:
        headers = {"Content-Type": "application/json"}
        if LLM_API_KEY:
            headers["Authorization"] = f"Bearer {LLM_API_KEY}"
        payload = {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0,
            "max_tokens": 100,
        }
        resp = httpx.post(LLM_API_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        return result
    except Exception as e:
        print(f"[monitor-agent] LLM error: {e}")
        return "LLM_ERROR"


def _call_do(tool: str, params: dict) -> str:
    payload = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": tool, "arguments": params}, "id": 1}
    try:
        resp = httpx.post(DO_MCP_URL, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        contents = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in contents)
    except Exception as e:
        return f"[ERROR] {e}"


def _check_droplets() -> list[dict]:
    results = []
    raw = _call_do("list_droplets", {})
    for line in raw.strip().split("\n"):
        if line.startswith("Droplets:") or line.startswith("No managed"):
            continue
        parts = line.strip().split()
        if len(parts) >= 2:
            dname = parts[0]
            status = parts[1]
            result = {"name": dname, "status": status, "ip": parts[-1] if len(parts) > 2 else "-"}
            if status == "off":
                print(f"[monitor-agent] DO off: {dname}, orchestrator'a bildiriliyor...")
                fix_result = _call_orchestrator(f"{dname} dropleti kapali, ensure_running ile ac. do-agent kullan")
                result["auto_fix"] = fix_result
                result["fixed"] = True
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                with _alert_lock:
                    _alert_history.append({
                        "time": ts,
                        "host": f"do:{dname}",
                        "service": "droplet",
                        "action": "orchestrator",
                        "result": fix_result[:120],
                    })
                print(f"[monitor-agent] ORCHESTRATOR {dname}: {fix_result[:60]}")
            else:
                result["fixed"] = False
            results.append(result)
    return results


def _call_mcp(tool: str, params: dict) -> str:
    import httpx
    payload = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": tool, "arguments": params}, "id": 1}
    try:
        resp = httpx.post(f"{DEBIAN_MCP_URL}/mcp", json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        contents = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in contents)
    except Exception as e:
        return f"[ERROR] {e}"


def _call_vcenter_agent(tool: str, params: dict) -> str:
    try:
        resp = httpx.post(
            f"{GATEWAY_URL}/api/gateway/agent/vcenter-agent/ask",
            json={"tool_name": tool, "params": params},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        contents = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in contents)
    except Exception as e:
        return f"[ERROR] {e}"


def _check_vcenter_vms() -> list[dict]:
    results = []
    raw = _call_vcenter_agent("list_vms", {})
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
                fix_result = _call_orchestrator(f"{vm_name} VM'si kapali, ensure_running ile ac. vcenter-agent kullan")
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


MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "60"))
CRITICAL_SERVICES = os.getenv("CRITICAL_SERVICES", "ssh,nginx,cron").split(",")
CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "0.8"))
MEM_THRESHOLD = float(os.getenv("MEM_THRESHOLD", "85"))
DISK_THRESHOLD = int(os.getenv("DISK_THRESHOLD", "85"))
LOG_ERROR_LINES = int(os.getenv("LOG_ERROR_LINES", "5"))
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
AUTO_FIX = os.getenv("MONITOR_AUTO_FIX", "true").lower() == "true"


def _reset_budget():
    try:
        httpx.post(f"{GATEWAY_URL}/api/gateway/reset-budget/monitor-agent", timeout=5)
    except Exception:
        pass

TOOLS = [
    {
        "name": "check_all",
        "description": "Check CPU, memory, disk, services, logs, DO droplets, and vCenter VMs",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_host",
        "description": "Full health check on a single host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
            },
            "required": ["host_name"],
        },
    },
    {
        "name": "status_report",
        "description": "Get latest monitoring status report and alert history",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "fix_service",
        "description": "Try to restart a failed service on a host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "Host name from config"},
                "service": {"type": "string", "description": "Service name to restart"},
            },
            "required": ["host_name", "service"],
        },
    },
]

_agent_instance = None
_status_cache = {}
_status_lock = threading.Lock()
_alert_history: list[dict] = []
_alert_lock = threading.Lock()
_cycle_running = False
_cycle_lock = threading.Lock()


def _get_agent():
    global _agent_instance
    return _agent_instance


def _call(tool: str, params: dict) -> str:
    return _call_mcp(tool, params)


def _get_hosts() -> list[str]:
    raw = _call_mcp("list_hosts", {})
    hosts = []
    for line in raw.strip().split("\n"):
        if ":" in line and not line.startswith("Configured"):
            name = line.split(":")[0].strip()
            if name:
                hosts.append(name)
    return hosts


def _restart_service(host: str, svc: str) -> str:
    try:
        raw = _call("service_restart", {"host_name": host, "service": svc})
        status = _call("service_status", {"host_name": host, "service": svc})
        if "active (running)" in status or "running" in status.lower().split("\n")[0]:
            return f"OK: {svc} restart edildi"
        return f"FAIL: {svc} restart basarisiz\n{status}"
    except Exception as e:
        return f"ERROR: {svc} restart hatasi: {e}"


def _check_host_internal(host: str) -> dict:
    result = {"host": host, "status": "ok", "alerts": [], "timestamp": time.time()}

    info_raw = _call("system_info", {"host_name": host})
    if info_raw.startswith(("[ERROR]", "[EXIT", "[SSH")):
        result["status"] = "error"
        result["alerts"].append(f"UNREACHABLE: {info_raw[:80]}")
        return result

    try:
        info = json.loads(info_raw)
        result["uptime"] = info.get("uptime", "")
        load_str = info.get("load_avg", "0, 0, 0")
        parts = load_str.replace(",", " ").split()
        if parts:
            load1 = float(parts[0])
            cores = int(info.get("cpu_cores", "1"))
            cpu_pct = (load1 / cores) * 100 if cores > 0 else 0
            result["cpu_load"] = round(cpu_pct, 1)
            if cpu_pct > CPU_THRESHOLD * 100:
                result["alerts"].append(f"YUKSEK CPU: %{cpu_pct:.0f}")
                result["status"] = "warn"

        mem = info.get("memory_used/total", "0/0")
        if "/" in mem:
            total_str, used_str = mem.split("/")
            total_v = int(total_str.replace("Mi", "").replace("Gi", "").strip())
            used_v = int(used_str.replace("Mi", "").replace("Gi", "").strip())
            if total_v > 0:
                mem_pct = (used_v / total_v) * 100
                result["memory_pct"] = round(mem_pct, 1)
                if mem_pct > MEM_THRESHOLD:
                    result["alerts"].append(f"YUKSEK MEM: %{mem_pct:.0f}")
                    result["status"] = "warn"

        disk = info.get("disk_used/total", "0/0")
        if "/" in disk:
            du, dt = disk.split("/")
            du_v = float(du.replace("G", "").replace("M", "").strip())
            dt_v = float(dt.replace("G", "").replace("M", "").strip())
            if dt_v > 0:
                disk_pct = (du_v / dt_v) * 100
                result["disk_pct"] = round(disk_pct, 1)
                if disk_pct > DISK_THRESHOLD:
                    result["alerts"].append(f"YUKSEK DISK: %{disk_pct:.0f}")
                    result["status"] = "warn"
    except Exception as e:
        result["alerts"].append(f"system_info HATA: {e}")
        result["status"] = "error"

    for svc in CRITICAL_SERVICES:
        svc = svc.strip()
        if not svc:
            continue
        try:
            raw = _call("service_status", {"host_name": host, "service": svc})
            if "active (running)" not in raw and "running" not in raw.lower().split("\n")[0]:
                result["alerts"].append(f"DOWN: {svc}")
                result["status"] = "error"
        except Exception as e:
            result["alerts"].append(f"{svc} HATA: {e}")

    try:
        log_raw = _call("journalctl", {"host_name": host, "lines": LOG_ERROR_LINES})
        errors = [l for l in log_raw.split("\n") if "error" in l.lower() or "fail" in l.lower() or "critical" in l.lower()]
        if errors:
            result["log_errors"] = errors[:5]
            result["alerts"].append(f"{len(errors)} log hatasi")
            if result["status"] == "ok":
                result["status"] = "warn"
    except Exception:
        pass

    return result


def _call_orchestrator(task: str) -> str:
    try:
        resp = httpx.post(
            f"{GATEWAY_URL}/api/gateway/agent/orchestrator-agent/ask",
            json={"tool_name": "ask", "params": {"task": task}},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        contents = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in contents)
    except Exception as e:
        return f"[ORCHESTRATOR ERROR] {e}"


def _auto_fix(host: str, svc: str) -> str | None:
    if not AUTO_FIX:
        return None
    fix_time = datetime.datetime.now().strftime("%H:%M:%S")
    task = f"{host} sunucusunda {svc} servisi down, kontrol et ve duzelt. sysadmin-agent kullan"
    result = _call_orchestrator(task)
    with _alert_lock:
        _alert_history.append({
            "time": fix_time,
            "host": host,
            "service": svc,
            "action": "orchestrator",
            "result": result[:120],
        })
    print(f"[monitor-agent] ORCHESTRATOR {host}/{svc}: {result[:80]}")
    return result


def _run_monitor_cycle():
    global _cycle_running
    if not _cycle_lock.acquire(blocking=False):
        with _status_lock:
            return _status_cache.get("results", [])
    try:
        _cycle_running = True
        hosts = _get_hosts()
        results = []
        for host in hosts:
            try:
                res = _check_host_internal(host)
                for alert in res.get("alerts", []):
                    if alert.startswith("DOWN:"):
                        svc = alert.replace("DOWN:", "").strip()
                        fix_result = _auto_fix(host, svc)
                results.append(res)
            except Exception as e:
                results.append({"host": host, "status": "error", "alerts": [str(e)], "timestamp": time.time()})

        droplets = _check_droplets()
        with _status_lock:
            _status_cache["droplets"] = droplets

        vms = _check_vcenter_vms()
        with _status_lock:
            _status_cache["vms"] = vms

        with _status_lock:
            _status_cache["last_run"] = time.time()
            _status_cache["results"] = results
            _status_cache["summary"] = _format_summary(results, droplets, vms)
        return results
    finally:
        _cycle_running = False
        _cycle_lock.release()


def _format_summary(results: list, droplets: list = None, vms: list = None) -> str:
    total = len(results)
    ok = sum(1 for r in results if r["status"] == "ok")
    warn = sum(1 for r in results if r["status"] == "warn")
    err = sum(1 for r in results if r["status"] == "error")
    lines = [f"MONITOR RAPORU - {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
             f"Toplam: {total} host | OK: {ok} | Uyari: {warn} | HATA: {err}"]
    for r in results:
        alerts = r.get("alerts", [])
        if alerts:
            lines.append(f"\n{r['host']} [{r['status'].upper()}]:")
            for a in alerts:
                lines.append(f"  ! {a}")
        else:
            lines.append(f"\n{r['host']}: saglikli")
    if droplets:
        lines.append(f"\n--- DO Droplets ({len(droplets)}) ---")
        for d in droplets:
            icon = "✓" if not d.get("fixed") else "🔧"
            lines.append(f"  {icon} {d['name']}: {d['status']}")
    if vms:
        lines.append(f"\n--- vCenter VMs ({len(vms)}) ---")
        for vm in vms:
            icon = "✓" if not vm.get("fixed") else "🔧"
            lines.append(f"  {icon} {vm['name']}: {vm['power_state']}")
    return "\n".join(lines)


def _background_monitor():
    while True:
        _reset_budget()
        try:
            results = _run_monitor_cycle()
            has_issue = any(r["status"] != "ok" for r in results)
            if has_issue:
                summary = _status_cache.get("summary", "")
                first_line = summary.split("\n")[0] if summary else ""
                print(f"[monitor-agent] {first_line}")
        except Exception as e:
            print(f"[monitor-agent] Monitor error: {e}")
        time.sleep(MONITOR_INTERVAL)


def _check_all(args: dict) -> str:
    _reset_budget()
    results = _run_monitor_cycle()
    alerts = []
    for r in results:
        for a in r.get("alerts", []):
            alerts.append(f"[{r['host']}] {a}")
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = [f"=== Monitor {ts} ==="]
    ok_count = sum(1 for r in results if r["status"] == "ok")
    out.append(f"OK: {ok_count}/{len(results)}")
    if alerts:
        out.append(f"\nALERTLER ({len(alerts)}):")
        out.extend(alerts)
    else:
        out.append("\nTum sistemler saglikli.")
    for r in results:
        if r["status"] != "ok":
            out.append(f"\n{r['host']} [{r['status'].upper()}]")
            if "cpu_load" in r:
                out.append(f"  CPU: %{r['cpu_load']}")
            if "memory_pct" in r:
                out.append(f"  MEM: %{r['memory_pct']}")
            if "disk_pct" in r:
                out.append(f"  DISK: %{r['disk_pct']}")
    with _status_lock:
        droplets = _status_cache.get("droplets", [])
        if droplets:
            out.append(f"\n--- DO Droplets ({len(droplets)}) ---")
            for d in droplets:
                icon = "✓" if not d.get("fixed") else "🔧"
                out.append(f"  {icon} {d['name']}: {d['status']}")
                if d.get("fixed"):
                    out.append(f"      Auto-fix: {d.get('auto_fix', '')[:80]}")
        vms = _status_cache.get("vms", [])
        if vms:
            out.append(f"\n--- vCenter VMs ({len(vms)}) ---")
            for vm in vms:
                icon = "✓" if not vm.get("fixed") else "🔧"
                out.append(f"  {icon} {vm['name']}: {vm['power_state']}")
                if vm.get("fixed"):
                    out.append(f"      Auto-fix: {vm.get('auto_fix', '')[:80]}")
    with _alert_lock:
        if _alert_history:
            out.append(f"\nSon mudahaleler ({len(_alert_history)}):")
            for a in _alert_history[-5:]:
                status = "✓" if "OK" in a["result"] else "✗"
                out.append(f"  {status} {a['time']} {a['host']}/{a['service']} -> {a['result'][:50]}")
    return "\n".join(out)


def _check_host(args: dict) -> str:
    host = args.get("host_name", "")
    res = _check_host_internal(host)
    out = [f"=== {host} ==="]
    out.append(f"Durum: {res['status'].upper()}")
    if "uptime" in res:
        out.append(f"Uptime: {res['uptime']}")
    if "cpu_load" in res:
        out.append(f"CPU: %{res['cpu_load']}")
    if "memory_pct" in res:
        out.append(f"MEM: %{res['memory_pct']}")
    if "disk_pct" in res:
        out.append(f"DISK: %{res['disk_pct']}")
    if res.get("alerts"):
        out.append("\nALERTLER:")
        out.extend(f"  ! {a}" for a in res["alerts"])
    if res.get("log_errors"):
        out.append("\nSon log hatalari:")
        out.extend(f"  - {e}" for e in res["log_errors"])
    return "\n".join(out)


def _status_report(args: dict) -> str:
    with _status_lock:
        summary = _status_cache.get("summary", "Henuz monitor calismadi.")
        droplets = _status_cache.get("droplets", [])
        if droplets:
            summary += f"\n\n--- DO Droplets ({len(droplets)}) ---"
            for d in droplets:
                icon = "✓" if not d.get("fixed") else "🔧"
                summary += f"\n  {icon} {d['name']}: {d['status']}"
        vms = _status_cache.get("vms", [])
        if vms:
            summary += f"\n\n--- vCenter VMs ({len(vms)}) ---"
            for vm in vms:
                icon = "✓" if not vm.get("fixed") else "🔧"
                summary += f"\n  {icon} {vm['name']}: {vm['power_state']}"
    with _alert_lock:
        if _alert_history:
            summary += f"\n\nSON MUDAHALELER ({len(_alert_history)}):"
            for a in _alert_history[-10:]:
                status = "✓" if "OK" in a["result"] else "✗"
                summary += f"\n  {status} {a['time']} {a['host']}/{a['service']} -> {a['result'][:60]}"
    return summary


def _fix_service(args: dict) -> str:
    host = args.get("host_name", "")
    svc = args.get("service", "")
    return _restart_service(host, svc)


TOOL_FUNCS = {
    "check_all": _check_all,
    "check_host": _check_host,
    "status_report": _status_report,
    "fix_service": _fix_service,
}

if __name__ == "__main__":
    port = int(os.getenv("MONITOR_AGENT_PORT", "8014"))
    agent = BaseAgent(
        name="monitor-agent",
        description="System monitoring: CPU, memory, disk, services, logs on all hosts",
        tools=TOOLS,
        tool_funcs=TOOL_FUNCS,
        port=port,
        platform="local",
    )
    _agent_instance = agent
    t = threading.Thread(target=_background_monitor, daemon=True)
    t.start()
    agent.run()
