"""
Orchestrator Agent: LLM-powered agent that plans and executes tasks
by calling MCP tools through the gateway.
"""
import os, json, httpx
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
from agents.base_agent import BaseAgent

LLM_API_URL = os.getenv("LLM_API_URL", "http://localhost:11434/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-coder:480b-cloud")
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
0. If the task is a simple question (math, trivia, chat) that needs no tools, answer directly without TOOL lines
1. If tools are needed, output EXACTLY one TOOL line per step
2. Use ONLY agent names from the list above
3. Use ONLY tool names listed under that agent
4. Never use orchestrator-agent itself
5. Never use debian-mcp directly — use sysadmin-agent instead

IMPORTANT: For VM management use vcenter-agent:
- To list all VMs → use: vcenter-agent list_vms
- To check a VM's status → use: vcenter-agent vm_status {{"name": "vm_name"}}
- To power on a VM → use: vcenter-agent power_on {{"name": "vm_name"}}
- To power off a VM → use: vcenter-agent power_off {{"name": "vm_name"}}
- To ensure a VM is running → use: vcenter-agent ensure_running {{"name": "vm_name"}}
- To deploy a new VM from template → use: vcenter-agent deploy_vm {{"template_name": "...", "vm_name": "..."}}
- To check cluster resources → use: vcenter-agent cluster_resources
- To create a snapshot → use: vcenter-agent create_snapshot {{"name": "vm_name", "snapshot_name": "..."}}

Examples:
User: list all VMs
TOOL: vcenter-agent list_vms {{}}

User: check status of zeus VM
TOOL: vcenter-agent vm_status {{"name": "zeus"}}

User: power on the VM named zeus
TOOL: vcenter-agent power_on {{"name": "zeus"}}

User: list all hosts
TOOL: sysadmin-agent list_hosts {{}}

User: check cpu on zeus (server is running)
TOOL: sysadmin-agent host_status {{"host_name": "zeus"}}

User: deploy app to hera
TOOL: devops-agent deploy_service {{"host_name": "hera", "service": "myapp"}}
TOOL: do-agent ensure_all_running {{}}
"""


def _ask_llm(prompt: str) -> str:
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.1,
    }
    try:
        resp = httpx.post(LLM_API_URL, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[LLM error: {e}]"


def _ask(args: dict) -> str:
    task = args.get("task", "")
    registry_info = _get_registry_summary()
    prompt = SYSTEM_PROMPT.format(registry=registry_info)
    prompt += f"\n\nUser task: {task}\n\nPlan (one TOOL line per step):"

    raw_llm = _ask_llm(prompt)
    lines = raw_llm.strip().split("\n")

    # Debug: save raw response
    import sys
    print(f"[ORCH DEBUG] RAW: {raw_llm[:200]}", file=sys.stderr, flush=True)

    steps = []
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
                steps.append({"agent": agent, "tool": tool, "params": params, "status": "error", "error": str(je)})
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
            steps.append({"agent": agent, "tool": tool, "params": params, "status": "ok", "result": text[:500]})
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            executed.append(f"[{agent}/{tool}] ERROR: {err}")
            steps.append({"agent": agent, "tool": tool, "params": params, "status": "error", "error": err})

    if not found_any_tool:
        return raw_llm.strip() or f"LLM response did not contain TOOL lines.\n\nRaw:\n{raw_llm[:500]}"

    all_output = "\n\n".join(executed)
    summary_prompt = f"""Task: {task}

Results from tools:
{all_output}

Summarize what was done in 2-3 sentences in Turkish:"""
    summary = _ask_llm(summary_prompt)
    final = f"=== Execution Results ===\n\n{all_output}\n\n=== Summary ===\n{summary}"

    # Save execution history to gateway
    try:
        httpx.post(
            f"{GATEWAY_URL}/api/gateway/orchestrator/history",
            json={
                "task": task,
                "plan": raw_llm,
                "steps": steps,
                "summary": summary,
                "result": final,
            },
            timeout=5,
        )
    except Exception:
        pass

    return final


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
