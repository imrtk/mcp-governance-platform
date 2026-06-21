import os
import re
import yaml

from agent_os.mcp_gateway import MCPGateway, GovernancePolicy, ApprovalStatus, ResponsePolicy


def load_policy_from_yaml(path: str = "policies/default-policy.yaml") -> tuple[GovernancePolicy, list[str]]:
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


class GatewayState:
    """Policy engine and tool call interception."""

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

    def check_destructive(self, tool_name: str, params: dict) -> tuple[bool, str]:
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

    def intercept(self, agent_id: str, tool_name: str, params: dict, audit_sink=None) -> tuple[bool, str]:
        safe, reason = self.check_destructive(tool_name, params)
        if not safe:
            if audit_sink:
                audit_sink.append(agent_id, tool_name, params, False, reason)
            return False, reason
        allowed, reason = self.gateway.intercept_tool_call(agent_id, tool_name, params)
        if audit_sink:
            audit_sink.append(agent_id, tool_name, params, allowed, reason)
        return allowed, reason

    def scan_response(self, agent_id: str, tool_name: str, content: str):
        return self.gateway.intercept_tool_response(agent_id, tool_name, content)

    def reset_budget(self, agent_id: str):
        self.gateway.reset_agent_budget(agent_id)

    def reload(self):
        self.policy, yaml_sensitive = load_policy_from_yaml(self.policy_path)
        self._init_gateway(yaml_sensitive)


state = GatewayState()
