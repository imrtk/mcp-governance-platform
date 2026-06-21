import argparse
import json
import httpx
import sys

GATEWAY_URL = "http://localhost:8080"


def _set_gateway(url: str):
    import mcp_governance.cli.main as m
    m.GATEWAY_URL = url


def _get(path: str) -> dict:
    import mcp_governance.cli.main as m
    r = httpx.get(f"{m.GATEWAY_URL}{path}", timeout=10)
    r.raise_for_status()
    return r.json()


def _post(path: str, data: dict = None) -> dict:
    import mcp_governance.cli.main as m
    r = httpx.post(f"{m.GATEWAY_URL}{path}", json=data or {}, timeout=10)
    r.raise_for_status()
    return r.json()


def cmd_status(args):
    health = _get("/health")
    gw = _get("/api/gateway/health")
    print(f"Platform: {health.get('message')}")
    print(f"Status:   {health.get('status')}")
    print(f"Policy:   {gw.get('policy')}")
    print(f"Mode:     {gw.get('mode')}")


def cmd_policy(args):
    if args.policy_cmd == "list":
        data = _get("/api/gateway/policy")
        print(f"Policy: {data['name']}")
        print(f"Allowed tools ({len(data['allowed_tools'])}):")
        for t in sorted(data['allowed_tools']):
            print(f"  ├ {t}")
        print(f"\nBlocked patterns ({len(data['blocked_patterns'])}):")
        for p in data['blocked_patterns']:
            print(f"  ├ {p}")
        print(f"\nRules ({len(data['rules'])}):")
        for r in data['rules']:
            print(f"  [{r['action']}] {r['name']}")
    elif args.policy_cmd == "yaml":
        data = _get("/api/gateway/policy/yaml")
        print(data['yaml'])
    else:
        print("use: policy list|yaml")


def cmd_agents(args):
    if args.agents_cmd == "list":
        data = _get("/api/gateway/agent/list")
        print(f"Agents ({len(data['agents'])}):")
        for a in sorted(data['agents']):
            print(f"  ├ {a}")
    else:
        print("use: agents list")


def cmd_audit(args):
    data = _get(f"/api/gateway/audit?limit={args.limit}")
    print(f"Audit log ({len(data)} entries):")
    for e in data:
        ts = e.get('timestamp', 0)
        agent = e.get('agent_id', '?')
        tool = e.get('tool_name', '?')
        allowed = "ALLOW" if e.get('allowed') else "BLOCK"
        reason = e.get('reason', '')[:60]
        print(f"  [{allowed}] {agent}/{tool} — {reason}")


def cmd_mcp(args):
    if args.mcp_cmd == "list":
        data = _get("/api/registry/servers")
        print(f"MCP Servers ({len(data)}):")
        for s in data:
            status_icon = "✓" if s['status'] == 'running' else "✗"
            caps = ", ".join(s.get('capabilities', [])[:5])
            print(f"  {status_icon} {s['name']:20s} {s['url']:30s} [{s['status']}]")
            if caps:
                print(f"     tools: {caps}")
    elif args.mcp_cmd == "check":
        data = _get("/api/registry/servers")
        all_ok = True
        for s in data:
            url = s.get('url', '')
            if not url:
                continue
            try:
                r = httpx.post(f"{url}/mcp", json={
                    "jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1
                }, timeout=5)
                if r.status_code == 200:
                    tools = r.json().get("result", {}).get("tools", [])
                    print(f"  ✓ {s['name']:20s} ({len(tools)} tools)")
                else:
                    print(f"  ✗ {s['name']:20s} HTTP {r.status_code}")
                    all_ok = False
            except Exception as e:
                print(f"  ✗ {s['name']:20s} {e}")
                all_ok = False
        if all_ok:
            print("\nAll MCP servers healthy")
        else:
            print("\nSome MCP servers unreachable")
            sys.exit(1)
    else:
        print("use: mcp list|check")


def cmd_orch(args):
    data = _get(f"/api/gateway/orchestrator/history?limit={args.limit}")
    print(f"Orchestrator history ({len(data)} entries):")
    for e in data:
        ts = e.get('timestamp', 0)
        task = e.get('task', '')[:80]
        steps = len(e.get('steps', []))
        summary = e.get('summary', '')[:100]
        print(f"  {ts:.0f} | {task}")
        print(f"       {steps} steps | {summary}")


def cmd_govern(args):
    data = _post("/api/gateway/govern", {
        "agent_id": args.agent,
        "tool_name": args.tool,
        "params": json.loads(args.params) if args.params else {},
    })
    if data.get('allowed'):
        print(f"ALLOW: {data['reason']}")
    else:
        print(f"BLOCK: {data['reason']}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="MCP Governance CLI")
    parser.add_argument("--gateway", default=GATEWAY_URL, help="Gateway URL (default: http://localhost:8080)")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="Platform status")

    p_policy = sub.add_parser("policy", help="Policy management")
    p_policy.add_argument("policy_cmd", nargs="?", choices=["list", "yaml"], default="list")

    p_agents = sub.add_parser("agents", help="Agent management")
    p_agents.add_argument("agents_cmd", nargs="?", choices=["list"], default="list")

    p_audit = sub.add_parser("audit", help="Show audit log")
    p_audit.add_argument("--limit", type=int, default=20)

    p_mcp = sub.add_parser("mcp", help="MCP server management")
    p_mcp.add_argument("mcp_cmd", nargs="?", choices=["list", "check"], default="list")

    p_orch = sub.add_parser("orch", help="Orchestrator history")
    p_orch.add_argument("--limit", type=int, default=10)

    p_gov = sub.add_parser("govern", help="Test governance on a tool call")
    p_gov.add_argument("--agent", default="cli")
    p_gov.add_argument("--tool", required=True)
    p_gov.add_argument("--params", default="{}")

    args = parser.parse_args()

    if args.command:
        _set_gateway(args.gateway)
    else:
        parser.print_help()
        return

    cmds = {
        "status": cmd_status,
        "policy": cmd_policy,
        "agents": cmd_agents,
        "audit": cmd_audit,
        "mcp": cmd_mcp,
        "orch": cmd_orch,
        "govern": cmd_govern,
    }
    cmds.get(args.command, lambda _: parser.print_help())(args)


if __name__ == "__main__":
    main()
