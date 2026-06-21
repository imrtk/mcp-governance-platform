import httpx
import asyncio
from fastapi import APIRouter, HTTPException
from mcp_governance.policy.models import ToolCallRequest, ToolCallResponse
from mcp_governance.policy.engine import state
from mcp_governance.audit.store import audit_store
from registry.api import get_server_url

router = APIRouter(tags=["govern"])


@router.post("/govern")
async def govern_request(req: ToolCallRequest):
    allowed, reason = state.intercept(req.agent_id, req.tool_name, req.params, audit_sink=audit_store)
    if not allowed:
        return ToolCallResponse(allowed=False, reason=reason)
    return ToolCallResponse(allowed=True, reason=reason, scanned=True)


@router.post("/govern/{mcp_name}")
async def govern_mcp_request(mcp_name: str, req: ToolCallRequest):
    allowed, reason = state.intercept(req.agent_id, req.tool_name, req.params, audit_sink=audit_store)
    if not allowed:
        return ToolCallResponse(allowed=False, reason=reason)

    server_url = get_server_url(mcp_name)
    if not server_url:
        raise HTTPException(status_code=404, detail=f"MCP server '{mcp_name}' not found")

    mcp_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": req.tool_name, "arguments": req.params},
        "id": 1,
    }
    try:
        resp = await asyncio.get_event_loop().run_in_executor(
            None, lambda: httpx.post(f"{server_url}/mcp", json=mcp_payload, timeout=30)
        )
        resp.raise_for_status()
        result = resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Upstream MCP server error: {e}")

    response_content = str(result.get("result", ""))
    scan_result = state.scan_response(req.agent_id, req.tool_name, response_content)
    if not scan_result.allowed:
        return ToolCallResponse(allowed=False, reason=scan_result.reason, scanned=True)
    return ToolCallResponse(allowed=True, reason=reason, result=result, scanned=True)


@router.post("/reset-budget/{agent_id}")
async def reset_budget(agent_id: str):
    state.reset_budget(agent_id)
    return {"status": "ok", "agent_id": agent_id}


@router.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "AGT Central Gateway",
        "policy": state.policy.name,
        "mode": "real",
    }
