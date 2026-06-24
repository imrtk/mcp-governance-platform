"""Zabbix Agent: monitoring management via zabbix-mcp."""
import os
from agents.base_agent import BaseAgent

MCP_NAME = "zabbix-mcp"

TOOLS = [
    {
        "name": "zabbix_list_hosts",
        "description": "List all monitored hosts with status and IP",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Filter by host name", "default": ""},
                "status": {"type": "string", "description": "monitored, unmonitored, all", "default": "monitored"},
            },
        },
    },
    {
        "name": "zabbix_get_host",
        "description": "Get detailed host info",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Host name or ID"},
            },
            "required": ["host"],
        },
    },
    {
        "name": "zabbix_list_alerts",
        "description": "Get active triggers/problems",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50},
                "severity": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "zabbix_get_metrics",
        "description": "Get metric values for a host",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "item_key": {"type": "string", "default": ""},
            },
            "required": ["host"],
        },
    },
    {
        "name": "zabbix_get_events",
        "description": "Get recent Zabbix events",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50},
                "severity": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "zabbix_create_host",
        "description": "Add a host to Zabbix",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "ip": {"type": "string"},
                "template_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["host", "ip"],
        },
    },
    {
        "name": "zabbix_delete_host",
        "description": "Remove a host from Zabbix",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
            },
            "required": ["host"],
        },
    },
    {
        "name": "zabbix_acknowledge_event",
        "description": "Acknowledge a Zabbix event",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "message": {"type": "string", "default": "Acknowledged by MCP"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "zabbix_get_dashboard",
        "description": "Get monitoring summary",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_agent_instance = None


def _get_agent():
    global _agent_instance
    return _agent_instance


def _call(tool: str, params: dict) -> str:
    agent = _get_agent()
    return agent._call_gateway(tool, params, MCP_NAME)


def _list_hosts(args: dict) -> str:
    return _call("zabbix_list_hosts", {"pattern": args.get("pattern", ""), "status": args.get("status", "monitored")})


def _get_host(args: dict) -> str:
    return _call("zabbix_get_host", {"host": args.get("host", "")})


def _list_alerts(args: dict) -> str:
    return _call("zabbix_list_alerts", {"limit": args.get("limit", 50), "severity": args.get("severity", "")})


def _get_metrics(args: dict) -> str:
    return _call("zabbix_get_metrics", {"host": args.get("host", ""), "item_key": args.get("item_key", "")})


def _get_events(args: dict) -> str:
    return _call("zabbix_get_events", {"limit": args.get("limit", 50), "severity": args.get("severity", "")})


def _create_host(args: dict) -> str:
    return _call("zabbix_create_host", {
        "host": args.get("host", ""),
        "ip": args.get("ip", ""),
        "template_ids": args.get("template_ids", []),
    })


def _delete_host(args: dict) -> str:
    return _call("zabbix_delete_host", {"host": args.get("host", "")})


def _acknowledge_event(args: dict) -> str:
    return _call("zabbix_acknowledge_event", {
        "event_id": args.get("event_id", ""),
        "message": args.get("message", "Acknowledged by MCP"),
    })


def _get_dashboard(args: dict) -> str:
    return _call("zabbix_get_dashboard", {})


TOOL_FUNCS = {
    "zabbix_list_hosts": _list_hosts,
    "zabbix_get_host": _get_host,
    "zabbix_list_alerts": _list_alerts,
    "zabbix_get_metrics": _get_metrics,
    "zabbix_get_events": _get_events,
    "zabbix_create_host": _create_host,
    "zabbix_delete_host": _delete_host,
    "zabbix_acknowledge_event": _acknowledge_event,
    "zabbix_get_dashboard": _get_dashboard,
}

if __name__ == "__main__":
    port = int(os.getenv("ZABBIX_AGENT_PORT", "8031"))
    agent = BaseAgent(
        name="zabbix-agent",
        description="Zabbix monitoring management: hosts, alerts, metrics, events",
        tools=TOOLS,
        tool_funcs=TOOL_FUNCS,
        port=port,
        platform="local",
    )
    _agent_instance = agent
    agent.run()
