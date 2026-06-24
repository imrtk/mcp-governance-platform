"""PostgreSQL Agent: database queries and alert logging via pgsql-mcp."""
import os, json
from agents.base_agent import BaseAgent

MCP_NAME = "pgsql-mcp"

TOOLS = [
    {
        "name": "pgsql_query",
        "description": "Execute a read-only SQL SELECT query. Returns JSON results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT query to execute"},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "pgsql_insert_alert",
        "description": "Insert an alert record into the database.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source agent name"},
                "level": {"type": "string", "description": "Alert level: info/warn/error", "default": "info"},
                "host": {"type": "string", "description": "Host name", "default": ""},
                "service": {"type": "string", "description": "Service name", "default": ""},
                "message": {"type": "string", "description": "Alert message"},
                "action": {"type": "string", "description": "Action taken", "default": ""},
                "result": {"type": "string", "description": "Action result", "default": ""},
            },
            "required": ["source", "message"],
        },
    },
    {
        "name": "pgsql_insert_metric",
        "description": "Insert a performance metric. Fields: source, metric, value, labels.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source agent name"},
                "metric": {"type": "string", "description": "Metric name"},
                "value": {"type": "number", "description": "Metric value"},
                "labels": {"type": "object", "description": "Optional labels", "default": {}},
            },
            "required": ["source", "metric", "value"],
        },
    },
    {
        "name": "pgsql_get_alerts",
        "description": "Query recent alerts with optional filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of alerts", "default": 50},
                "level": {"type": "string", "description": "Filter: info/warn/error", "default": ""},
                "host": {"type": "string", "description": "Filter by host", "default": ""},
                "source": {"type": "string", "description": "Filter by source agent", "default": ""},
            },
        },
    },
    {
        "name": "pgsql_list_tables",
        "description": "List all tables in the database.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pgsql_describe_table",
        "description": "Get column info for a table.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name"},
            },
            "required": ["table"],
        },
    },
    {
        "name": "pgsql_admin_exec",
        "description": "Execute INSERT/UPDATE/DELETE SQL (admin only).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL to execute"},
            },
            "required": ["sql"],
        },
    },
]

_agent_instance = None


def _get_agent():
    global _agent_instance
    return _agent_instance


def _call(tool: str, params: dict) -> str:
    agent = _get_agent()
    return agent._call_gateway(tool, params, MCP_NAME)


def _query(args: dict) -> str:
    return _call("pgsql_query", {"sql": args.get("sql", ""), "params": args.get("params", [])})


def _insert_metric(args: dict) -> str:
    return _call("pgsql_insert_metric", {
        "source": args.get("source", ""),
        "metric": args.get("metric", ""),
        "value": args.get("value", 0),
        "labels": args.get("labels", {}),
    })


def _insert_alert(args: dict) -> str:
    return _call("pgsql_insert_alert", {
        "source": args.get("source", ""),
        "level": args.get("level", "info"),
        "host": args.get("host", ""),
        "service": args.get("service", ""),
        "message": args.get("message", ""),
        "action": args.get("action", ""),
        "result": args.get("result", ""),
    })


def _get_alerts(args: dict) -> str:
    return _call("pgsql_get_alerts", {
        "limit": args.get("limit", 50),
        "level": args.get("level", ""),
        "host": args.get("host", ""),
        "source": args.get("source", ""),
    })


def _list_tables(args: dict) -> str:
    return _call("pgsql_list_tables", {})


def _describe_table(args: dict) -> str:
    return _call("pgsql_describe_table", {"table": args.get("table", "")})


def _admin_exec(args: dict) -> str:
    return _call("pgsql_execute", {"sql": args.get("sql", ""), "params": args.get("params", [])})


TOOL_FUNCS = {
    "pgsql_query": _query,
    "pgsql_insert_alert": _insert_alert,
    "pgsql_insert_metric": _insert_metric,
    "pgsql_get_alerts": _get_alerts,
    "pgsql_list_tables": _list_tables,
    "pgsql_describe_table": _describe_table,
    "pgsql_admin_exec": _admin_exec,
}


def _insert_alert_direct(source, level, host, service, message, action, result):
    """Helper called directly by other agents to persist alerts."""
    return _call("pgsql_insert_alert", {
        "source": source, "level": level, "host": host, "service": service,
        "message": message, "action": action, "result": result,
    })


if __name__ == "__main__":
    port = int(os.getenv("PGSQL_AGENT_PORT", "8021"))
    agent = BaseAgent(
        name="pgsql-agent",
        description="PostgreSQL database agent: query, alerts, schema inspection",
        tools=TOOLS,
        tool_funcs=TOOL_FUNCS,
        port=port,
        platform="local",
    )
    _agent_instance = agent
    agent.run()
