from fastapi import APIRouter
from mcp_governance.audit.store import audit_store, agent_msg_log
from mcp_governance.policy.models import AuditEntryPayload

router = APIRouter(tags=["audit"])


@router.get("/audit")
async def get_audit(limit: int = 50):
    return audit_store.get_recent(limit)


@router.post("/audit/ingest")
async def ingest_audit(entry: AuditEntryPayload):
    audit_store.ingest(
        timestamp=entry.timestamp,
        agent_id=entry.agent_id,
        tool_name=entry.tool_name,
        parameters=entry.parameters,
        allowed=entry.allowed,
        reason=entry.reason,
        approval_status=entry.approval_status,
    )
    return {"status": "ok"}


@router.get("/agent/log")
async def get_agent_log(limit: int = 100):
    return agent_msg_log.get_recent(limit)
