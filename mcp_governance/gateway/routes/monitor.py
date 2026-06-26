import httpx
from fastapi import APIRouter

router = APIRouter(tags=["monitor"])


def _call_mcp(url: str, tool_name: str, args: dict) -> dict:
    payload = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": tool_name, "arguments": args}, "id": 1}
    resp = httpx.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


@router.get("/monitor/status")
async def get_monitor_status():
    url = "http://localhost:8014/mcp"
    try:
        result = _call_mcp(url, "status_report", {})
        text = result.get("result", {}).get("content", [{}])[0].get("text", "")
        lines = text.split("\n")
        hosts = []
        current_host = None
        for line in lines:
            if "[" in line and "]" in line and (line.strip().endswith("]:")):
                h = line.split("[")[0].strip()
                status = "error" if "HATA" in line or "ERROR" in line else "warning" if "Uyari" in line or "WARN" in line else "ok"
                current_host = {"name": h, "status": status, "issues": []}
                hosts.append(current_host)
            elif current_host and "!" in line:
                current_host["issues"].append(line.split("!")[-1].strip())
        return {"ok": True, "hosts": hosts, "raw": text}
    except Exception as e:
        return {"ok": False, "error": str(e), "hosts": []}
