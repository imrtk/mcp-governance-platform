import os
import time
import threading
import uuid
import httpx
from collections import defaultdict
from fastapi import APIRouter, HTTPException
from mcp_governance.audit.store import orch_history, agent_msg_log
from mcp_governance.policy.models import ToolCallRequest, AgentMessage
from registry.api import get_server_url

router = APIRouter(tags=["agents"])

_agent_inboxes: dict[str, list[dict]] = defaultdict(list)
_agent_inbox_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


@router.post("/agent/message")
async def send_agent_message(msg: AgentMessage):
    if not msg.id:
        msg.id = str(uuid.uuid4())[:8]
    lock = _agent_inbox_locks[msg.to_agent]
    with lock:
        _agent_inboxes[msg.to_agent].append(msg.model_dump())
    return {"status": "queued", "message_id": msg.id, "to": msg.to_agent}


@router.get("/agent/messages/{agent_name}")
async def poll_agent_messages(agent_name: str):
    lock = _agent_inbox_locks[agent_name]
    with lock:
        msgs = list(_agent_inboxes.get(agent_name, []))
        _agent_inboxes[agent_name] = []
    return {"messages": msgs}


@router.get("/agent/list")
async def list_agents():
    all_agents = set(_agent_inboxes.keys())
    return {"agents": sorted(all_agents)}


@router.post("/agent/{agent_name}/ask")
async def ask_agent(agent_name: str, req: ToolCallRequest):
    server_url = get_server_url(agent_name)
    if not server_url:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found in registry")

    async with httpx.AsyncClient(timeout=300) as client:
        mcp_payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": req.tool_name, "arguments": req.params},
            "id": 1,
        }
        try:
            resp = await client.post(f"{server_url}/mcp", json=mcp_payload)
            resp.raise_for_status()
            result = resp.json()
            agent_msg_log.append({
                "timestamp": time.time(),
                "from": req.agent_id,
                "to": agent_name,
                "tool": req.tool_name,
                "params": req.params,
                "response": result,
            })
            return result
        except httpx.RequestError as e:
            agent_msg_log.append({
                "timestamp": time.time(),
                "from": req.agent_id,
                "to": agent_name,
                "tool": req.tool_name,
                "params": req.params,
                "response": {"error": str(e)},
            })
            raise HTTPException(status_code=502, detail=f"Agent '{agent_name}' unreachable: {e}")


@router.post("/orchestrator/history")
async def save_orch_history(payload: dict):
    entry = {
        "timestamp": time.time(),
        "task": payload.get("task", ""),
        "plan": payload.get("plan", ""),
        "steps": payload.get("steps", []),
        "summary": payload.get("summary", ""),
        "result": payload.get("result", ""),
    }
    orch_history.save(entry)
    return {"status": "ok"}


@router.get("/orchestrator/history")
async def get_orch_history(limit: int = 20):
    return orch_history.get_recent(limit)
