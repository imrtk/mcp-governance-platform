from pydantic import BaseModel
from typing import Optional


class ToolCallRequest(BaseModel):
    agent_id: str = "default-agent"
    tool_name: str
    params: dict = {}


class ToolCallResponse(BaseModel):
    allowed: bool
    reason: str
    result: Optional[dict] = None
    scanned: bool = False


class RuleModel(BaseModel):
    name: str
    condition: str
    action: str
    message: str = ""


class PolicyYAMLUpdate(BaseModel):
    yaml: str


class AuditEntryPayload(BaseModel):
    timestamp: float = 0
    agent_id: str = "unknown"
    tool_name: str = ""
    parameters: dict = {}
    allowed: bool = True
    reason: str = ""
    approval_status: str | None = None


class AgentMessage(BaseModel):
    id: str = ""
    from_agent: str
    to_agent: str
    type: str = "task"
    payload: dict = {}
    reply_to: str = ""
