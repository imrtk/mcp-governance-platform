"""
Orchestrator Agent: LLM-powered agent that plans and executes tasks
by calling MCP tools through the gateway using Ollama.
"""
import os, json, httpx
from agents.base_agent import BaseAgent

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://localhost:8080")

TOOLS = [
    {
        "name": "ask",
        "description": "Send a natural language task to the orchestrator. It will plan and execute using available agents and tools.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Natural language task description"},
            },
            "required": ["task"],
        },
    },
]


def _get_registry_summary() -> str:
    try:
        resp = httpx.get(f"{REGISTRY_URL}/api/registry/servers", timeout=5)
        servers = resp.json()
        lines = []
        for s in servers:
            tools = ", ".join(s.get("capabilities", []))
            lines.append(f"- {s['name']} ({s['platform']}, {s['status']}): [{tools}]")
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching registry: {e}"


SYSTEM_PROMPT = """You are an orchestration agent that controls MCP agents. Available agents and their tools:

{registry}

Rules:
1. Output EXACTLY one TOOL line per step
2. Use ONLY agent names from the list above
3. Use ONLY tool names listed under that agent
4. Never use orchestrator-agent itself
5. Never use debian-mcp directly — use sysadmin-agent instead

Agent guide (common tasks):
- For listing hosts → use: sysadmin-agent list_hosts
- For host status/monitoring → use: sysadmin-agent host_status
- For updates/upgrades → use: sysadmin-agent update_all
- For service management → use: sysadmin-agent restart_service
- For disk alerts → use: sysadmin-agent disk_alert
- For deployments → use: devops-agent deploy_service
- For containers/logs → use: devops-agent container_status or logs_tail
- For firewall/security → use: secops-agent firewall_status or security_audit

Format:
TOOL: <agent-name> <tool-name> {{"param": "value"}}

Example:
User: list all hosts
TOOL: sysadmin-agent list_hosts {{}}

User: check cpu on zeus
TOOL: sysadmin-agent host_status {{"host_name": "zeus"}}

User: deploy app to hera
TOOL: devops-agent deploy_service {{"host_name": "hera", "service": "myapp"}}
"""


def _ask_ollama(prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "temperature": 0.1,
    }
    try:
        resp = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        return f"[Ollama error: {e}]"


def _ask(args: dict) -> str:
    task = args.get("task", "")
    registry_info = _get_registry_summary()
    prompt = SYSTEM_PROMPT.format(registry=registry_info)
    prompt += f"\n\nUser task: {task}\n\nPlan (one TOOL line per step):"

    result = _ask_ollama(prompt)
    lines = result.strip().split("\n")

    # Debug: save raw response
    import sys
    print(f"[ORCH DEBUG] RAW: {result[:200]}", file=sys.stderr, flush=True)

    executed = []
    found_any_tool = False
    for line in lines:
        line = line.strip()
        if not line.startswith("TOOL:"):
            continue
        found_any_tool = True
        parts = line[len("TOOL:"):].strip().split(None, 2)
        if len(parts) < 2:
            executed.append(f"[SKIP] Bad TOOL line: {line}")
            continue
        agent = parts[0]
        tool = parts[1]
        params = {}
        if len(parts) >= 3:
            try:
                params = json.loads(parts[2])
            except json.JSONDecodeError as je:
                executed.append(f"[SKIP] JSON parse error for {tool}: {je}")
                continue
        try:
            print(f"[ORCH DEBUG] Calling {agent}/{tool} params={params}", file=sys.stderr, flush=True)
            r = httpx.post(
                f"{GATEWAY_URL}/api/gateway/agent/{agent}/ask",
                json={"agent_id": "orchestrator", "tool_name": tool, "params": params},
                timeout=30,
            )
            data = r.json()
            content = data.get("result", {}).get("content", [{}])
            text = content[0].get("text", str(data)) if content else str(data)
            executed.append(f"[{agent}/{tool}] OK:\n{text[:500]}")
        except Exception as e:
            executed.append(f"[{agent}/{tool}] ERROR: {type(e).__name__}: {e}")

    if not found_any_tool:
        return f"LLM response did not contain TOOL lines.\n\nRaw:\n{result[:500]}"

    all_output = "\n\n".join(executed)
    summary_prompt = f"""Task: {task}

Results from tools:
{all_output}

Summarize what was done in 2-3 sentences in Turkish:"""
    summary = _ask_ollama(summary_prompt)
    return f"=== Execution Results ===\n\n{all_output}\n\n=== Summary ===\n{summary}"


TOOL_FUNCS = {
    "ask": _ask,
}

if __name__ == "__main__":
    port = int(os.getenv("ORCHESTRATOR_AGENT_PORT", "8013"))
    agent = BaseAgent(
        name="orchestrator-agent",
        description="LLM-powered orchestrator: plans and executes tasks using all agents",
        tools=TOOLS,
        tool_funcs=TOOL_FUNCS,
        port=port,
        platform="local",
    )
    agent.run()
