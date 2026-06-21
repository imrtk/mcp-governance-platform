import os
import yaml
from fastapi import APIRouter, HTTPException
from mcp_governance.policy.engine import state
from mcp_governance.policy.models import RuleModel, PolicyYAMLUpdate

router = APIRouter(tags=["policy"])


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
    return {"status": "ok", "message": f"Rule '{rule_name}' deleted"}
