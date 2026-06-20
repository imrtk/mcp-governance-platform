import os
import re
import threading
import time
import uuid
import yaml
from pathlib import Path
from typing import Optional
from collections import defaultdict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_os.mcp_gateway import MCPGateway, GovernancePolicy, ApprovalStatus, ResponsePolicy


def load_policy_from_yaml(path: str = "policies/default-policy.yaml") -> GovernancePolicy:
    with open(path) as f:
        data = yaml.safe_load(f)

    allowed_tools = []
    blocked_patterns = []
    sensitive_tools = []
    name = data.get("name", "default")

    for rule in data.get("rules", []):
        action = rule.get("action", "deny")
        condition = rule.get("condition", "")

        if action == "allow":
            if "tool_name in" in condition:
                tools_str = condition.split("[")[1].split("]")[0]
                for t in tools_str.split(","):
                    allowed_tools.append(t.strip().strip('"').strip("'"))
        elif action == "require_approval":
            if "tool_name ==" in condition:
                tool = condition.split("==")[1].strip().strip('"').strip("'")
                allowed_tools.append(tool)
                sensitive_tools.append(tool)
        elif action == "deny":
            if "params contains" in condition:
                for match in re.findall(r'params contains "([^"]*)"', condition):
                    if match not in blocked_patterns:
                        blocked_patterns.append(match)

    return GovernancePolicy(
        name=name,
        allowed_tools=list(set(allowed_tools)),
        blocked_patterns=list(set(blocked_patterns)) if blocked_patterns else [],
        require_human_approval=False,
        log_all_calls=True,
        max_tool_calls=500,
    ), list(set(sensitive_tools))


POLICY_PATH = os.getenv("AGT_POLICY_PATH", "policies/default-policy.yaml")

# Shared audit store for entries from REST API gateway and external (Vibe) sources
_audit_store: list[dict] = []
_audit_lock = threading.Lock()


class GatewayState:
    def __init__(self):
        self.policy_path = POLICY_PATH
        self.policy, yaml_sensitive = load_policy_from_yaml(self.policy_path)
        self._init_gateway(yaml_sensitive)

    def _init_gateway(self, yaml_sensitive: list[str] | None = None):
        env_sensitive = os.getenv("AGT_SENSITIVE_TOOLS", "")
        sensitive = list(set(
            (yaml_sensitive or []) + (env_sensitive.split(",") if env_sensitive else [])
        ))

        def approval_callback(agent_id: str, tool_name: str, params: dict) -> ApprovalStatus:
            print(f"[APPROVAL] agent={agent_id} tool={tool_name} params={params}")
            return ApprovalStatus.APPROVED

        self.gateway = MCPGateway(
            self.policy,
            denied_tools=os.getenv("AGT_DENIED_TOOLS", "delete").split(","),
            sensitive_tools=sensitive if sensitive else None,
            approval_callback=approval_callback,
            enable_builtin_sanitization=True,
            response_policy=ResponsePolicy.LOG,
        )

    DESTRUCTIVE_COMMANDS = [
        "init 0", "init 6", "shutdown", "poweroff", "halt", "reboot",
        "rm -rf", "mkfs", "dd if=", "fdisk", " parted", "mkswap",
        "chmod 777 /", "chown -R", "> /dev/sd", ":(){ :|:& };:",
        "wget -O /", "curl -o /", "mv /", "cp /",
    ]

    def _check_destructive_command(self, tool_name: str, params: dict) -> tuple[bool, str]:
        if tool_name in ("reboot_host",):
            return False, "reboot_host is blocked by central policy"
        if tool_name in ("ssh_exec", "run_shell"):
            command = params.get("command", "")
            for pattern in self.DESTRUCTIVE_COMMANDS:
                if pattern in command.lower():
                    return False, f"Destructive command blocked: pattern '{pattern}' detected in command"
            if command.strip().startswith("sudo "):
                return False, "sudo commands are not allowed via SSH/shell"
        return True, ""

    def intercept(self, agent_id: str, tool_name: str, params: dict) -> tuple[bool, str]:
        safe, reason = self._check_destructive_command(tool_name, params)
        if not safe:
            with _audit_lock:
                _audit_store.append({
                    "timestamp": time.time(),
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                    "parameters": dict(params),
                    "allowed": False,
                    "reason": reason,
                    "approval_status": None,
                })
            return False, reason
        allowed, reason = self.gateway.intercept_tool_call(agent_id, tool_name, params)
        with _audit_lock:
            _audit_store.append({
                "timestamp": time.time(),
                "agent_id": agent_id,
                "tool_name": tool_name,
                "parameters": dict(params),
                "allowed": allowed,
                "reason": reason,
                "approval_status": None,
            })
        return allowed, reason

    def scan_response(self, agent_id: str, tool_name: str, content: str):
        return self.gateway.intercept_tool_response(agent_id, tool_name, content)

    def reset_budget(self, agent_id: str):
        self.gateway.reset_agent_budget(agent_id)

    def reload(self):
        self.policy, yaml_sensitive = load_policy_from_yaml(self.policy_path)
        self._init_gateway(yaml_sensitive)


state = GatewayState()

router = APIRouter(prefix="/api/gateway", tags=["gateway"])


class ToolCallRequest(BaseModel):
    agent_id: str = "default-agent"
    tool_name: str
    params: dict = {}


class ToolCallResponse(BaseModel):
    allowed: bool
    reason: str
    result: Optional[dict] = None
    scanned: bool = False


@router.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "AGT Central Gateway",
        "policy": state.policy.name,
        "mode": "real",
    }


@router.post("/govern", response_model=ToolCallResponse)
async def govern_request(req: ToolCallRequest):
    allowed, reason = state.intercept(req.agent_id, req.tool_name, req.params)
    if not allowed:
        return ToolCallResponse(allowed=False, reason=reason)
    return ToolCallResponse(allowed=True, reason=reason, scanned=True)


@router.post("/govern/{mcp_name}", response_model=ToolCallResponse)
async def govern_mcp_request(mcp_name: str, req: ToolCallRequest):
    allowed, reason = state.intercept(req.agent_id, req.tool_name, req.params)
    if not allowed:
        return ToolCallResponse(allowed=False, reason=reason)

    from registry.api import get_server_url

    server_url = get_server_url(mcp_name)
    if not server_url:
        raise HTTPException(status_code=404, detail=f"MCP server '{mcp_name}' not found")

    import httpx
    import asyncio

    mcp_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": req.tool_name, "arguments": req.params},
        "id": 1,
    }

    def _proxy():
        return httpx.post(f"{server_url}/mcp", json=mcp_payload, timeout=30)

    try:
        resp = await asyncio.get_event_loop().run_in_executor(None, _proxy)
        resp.raise_for_status()
        result = resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Upstream MCP server error: {e}")

    response_content = str(result.get("result", ""))
    scan_result = state.scan_response(req.agent_id, req.tool_name, response_content)

    if not scan_result.allowed:
        return ToolCallResponse(allowed=False, reason=scan_result.reason, scanned=True)

    return ToolCallResponse(
        allowed=True,
        reason=reason,
        result=result,
        scanned=True,
    )


@router.post("/reset-budget/{agent_id}")
async def reset_budget(agent_id: str):
    state.reset_budget(agent_id)
    return {"status": "ok", "agent_id": agent_id}


@router.get("/audit")
async def get_audit(limit: int = 50):
    with _audit_lock:
        entries = list(_audit_store[-limit:])
    return entries[::-1]


class AuditEntryPayload(BaseModel):
    timestamp: float = 0
    agent_id: str = "unknown"
    tool_name: str = ""
    parameters: dict = {}
    allowed: bool = True
    reason: str = ""
    approval_status: str | None = None


@router.post("/audit/ingest")
async def ingest_audit(entry: AuditEntryPayload):
    with _audit_lock:
        _audit_store.append({
            "timestamp": entry.timestamp or time.time(),
            "agent_id": entry.agent_id,
            "tool_name": entry.tool_name,
            "parameters": entry.parameters,
            "allowed": entry.allowed,
            "reason": entry.reason,
            "approval_status": entry.approval_status,
        })
    return {"status": "ok"}


@router.get("/policy")
async def get_policy():
    with open(state.policy_path) as f:
        raw = yaml.safe_load(f)
    return {
        "name": state.policy.name,
        "allowed_tools": state.policy.allowed_tools,
        "blocked_patterns": state.policy.blocked_patterns,
        "require_human_approval": state.policy.require_human_approval,
        "log_all_calls": state.policy.log_all_calls,
        "rules": raw.get("rules", []),
    }


@router.get("/policy/yaml")
async def get_policy_yaml():
    with open(state.policy_path) as f:
        return {"yaml": f.read()}


class PolicyYAMLUpdate(BaseModel):
    yaml: str


@router.put("/policy/yaml")
async def update_policy_yaml(body: PolicyYAMLUpdate):
    try:
        data = yaml.safe_load(body.yaml)
        if not data or "rules" not in data:
            raise HTTPException(status_code=400, detail="Invalid policy: missing 'rules'")
        with open(state.policy_path, "w") as f:
            f.write(body.yaml)
        state.reload()
        return {"status": "ok", "message": "Policy updated, gateway reloaded"}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")


class RuleModel(BaseModel):
    name: str
    condition: str
    action: str
    message: str = ""


@router.post("/policy/rules")
async def add_rule(rule: RuleModel):
    with open(state.policy_path) as f:
        data = yaml.safe_load(f) or {}
    names = [r["name"] for r in data.get("rules", [])]
    if rule.name in names:
        raise HTTPException(status_code=409, detail=f"Rule '{rule.name}' already exists")
    data.setdefault("rules", []).append(rule.model_dump(exclude_none=True))
    with open(state.policy_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    state.reload()
    return {"status": "ok", "message": f"Rule '{rule.name}' added"}


@router.put("/policy/rules/{rule_name}")
async def update_rule(rule_name: str, rule: RuleModel):
    with open(state.policy_path) as f:
        data = yaml.safe_load(f) or {}
    for i, r in enumerate(data.get("rules", [])):
        if r["name"] == rule_name:
            data["rules"][i] = rule.model_dump(exclude_none=True)
            with open(state.policy_path, "w") as f:
                yaml.dump(data, f, default_flow_style=False)
            state.reload()
            return {"status": "ok", "message": f"Rule '{rule_name}' updated"}
    raise HTTPException(status_code=404, detail=f"Rule '{rule_name}' not found")


@router.delete("/policy/rules/{rule_name}")
async def delete_rule(rule_name: str):
    with open(state.policy_path) as f:
        data = yaml.safe_load(f) or {}
    rules = [r for r in data.get("rules", []) if r["name"] != rule_name]
    if len(rules) == len(data.get("rules", [])):
        raise HTTPException(status_code=404, detail=f"Rule '{rule_name}' not found")
    data["rules"] = rules
    with open(state.policy_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    state.reload()
    return {"status": "ok", "message": f"Rule '{rule_name}' deleted'"}


# ─── Agent Message Bus ───────────────────────────────────────────────────────────

class AgentMessage(BaseModel):
    id: str = ""
    from_agent: str
    to_agent: str
    type: str = "task"
    payload: dict = {}
    reply_to: str = ""

_agent_inboxes: dict[str, list[dict]] = defaultdict(list)
_agent_inbox_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_agent_msg_log: list[dict] = []
_agent_msg_log_lock = threading.Lock()


@router.post("/agent/message")
async def send_agent_message(msg: AgentMessage):
    if not msg.id:
        msg.id = str(uuid.uuid4())[:8]
    lock = _agent_inbox_locks[msg.to_agent]
    with lock:
        _agent_inboxes[msg.to_agent].append(msg.model_dump())
    return {"status": "queued", "message_id": msg.id, "to": msg.to_agent}


class AgentPollResponse(BaseModel):
    messages: list[dict]


@router.get("/agent/messages/{agent_name}")
async def poll_agent_messages(agent_name: str):
    lock = _agent_inbox_locks[agent_name]
    with lock:
        msgs = list(_agent_inboxes.get(agent_name, []))
        _agent_inboxes[agent_name] = []
    return AgentPollResponse(messages=msgs)


@router.get("/agent/list")
async def list_agents():
    all_agents = set(_agent_inboxes.keys())
    return {"agents": sorted(all_agents)}


@router.post("/agent/{agent_name}/ask")
async def ask_agent(agent_name: str, req: ToolCallRequest):
    """Send a tool call request to another agent via MCP."""
    from registry.api import get_server_url

    server_url = get_server_url(agent_name)
    if not server_url:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found in registry")

    import httpx

    async with httpx.AsyncClient(timeout=180) as client:
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
            with _agent_msg_log_lock:
                _agent_msg_log.append({
                    "timestamp": time.time(),
                    "from": req.agent_id,
                    "to": agent_name,
                    "tool": req.tool_name,
                    "params": req.params,
                    "response": result,
                })
            return result
        except httpx.RequestError as e:
            with _agent_msg_log_lock:
                _agent_msg_log.append({
                    "timestamp": time.time(),
                    "from": req.agent_id,
                    "to": agent_name,
                    "tool": req.tool_name,
                    "params": req.params,
                    "response": {"error": str(e)},
                })
            raise HTTPException(status_code=502, detail=f"Agent '{agent_name}' unreachable: {e}")


@router.get("/agent/log")
async def get_agent_log(limit: int = 100):
    with _agent_msg_log_lock:
        entries = list(_agent_msg_log[-limit:])
    return sorted(entries, key=lambda x: x["timestamp"], reverse=True)


def _call_mcp_server(url: str, tool_name: str, args: dict) -> dict:
    import httpx
    payload = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": tool_name, "arguments": args}, "id": 1}
    resp = httpx.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


@router.get("/monitor/status")
async def get_monitor_status():
    url = "http://localhost:8014/mcp"
    try:
        result = _call_mcp_server(url, "status_report", {})
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
