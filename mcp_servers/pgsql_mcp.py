import os, json, ssl
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from pydantic import BaseModel

PGSQL_HOST = os.environ.get("PGSQL_HOST", "")
PGSQL_PORT = int(os.environ.get("PGSQL_PORT", "5432"))
PGSQL_DB = os.environ.get("PGSQL_DB", "")
PGSQL_USER = os.environ.get("PGSQL_USER", "")
PGSQL_PASSWORD = os.environ.get("PGSQL_PASSWORD", "")
PGSQL_ADMIN_USER = os.environ.get("PGSQL_ADMIN_USER", "")
PGSQL_ADMIN_PASSWORD = os.environ.get("PGSQL_ADMIN_PASSWORD", "")

_conn = None
_admin_conn = None


def _get_conn(admin=False):
    import psycopg2
    global _conn, _admin_conn
    if admin:
        if _admin_conn:
            try:
                _admin_conn.cursor().execute("SELECT 1")
                return _admin_conn
            except Exception:
                _admin_conn = None
        _admin_conn = psycopg2.connect(
            host=PGSQL_HOST, port=PGSQL_PORT, dbname=PGSQL_DB,
            user=PGSQL_ADMIN_USER, password=PGSQL_ADMIN_PASSWORD,
        )
        _admin_conn.autocommit = True
        return _admin_conn
    if _conn:
        try:
            _conn.cursor().execute("SELECT 1")
            return _conn
        except Exception:
            _conn = None
    _conn = psycopg2.connect(
        host=PGSQL_HOST, port=PGSQL_PORT, dbname=PGSQL_DB,
        user=PGSQL_USER, password=PGSQL_PASSWORD,
    )
    _conn.autocommit = True
    return _conn


def _init_schema():
    """Create tables if they don't exist."""
    if not PGSQL_HOST:
        return
    try:
        conn = _get_conn(admin=True)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                ts TIMESTAMPTZ DEFAULT NOW(),
                source TEXT NOT NULL,
                level TEXT DEFAULT 'info',
                host TEXT,
                service TEXT,
                message TEXT,
                action TEXT,
                result TEXT,
                raw JSONB
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orchestrator_log (
                id SERIAL PRIMARY KEY,
                ts TIMESTAMPTZ DEFAULT NOW(),
                task TEXT,
                agent TEXT,
                tool TEXT,
                params JSONB,
                status TEXT,
                result TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id SERIAL PRIMARY KEY,
                ts TIMESTAMPTZ DEFAULT NOW(),
                source TEXT NOT NULL,
                metric TEXT NOT NULL,
                value DOUBLE PRECISION,
                labels JSONB
            )
        """)
        cur.close()
    except Exception:
        pass


TOOLS = [
    {
        "name": "pgsql_query",
        "description": "Execute a read-only SQL SELECT query. Returns JSON results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT query to execute"},
                "params": {"type": "array", "description": "Optional query parameters", "items": {"type": "string"}},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "pgsql_execute",
        "description": "Execute INSERT/UPDATE/DELETE (requires admin user). Returns row count.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL to execute"},
                "params": {"type": "array", "description": "Optional query parameters", "items": {"type": "string"}},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "pgsql_insert_alert",
        "description": "Insert an alert record. Fields: source, level, host, service, message, action, result.",
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
        "name": "pgsql_get_alerts",
        "description": "Query recent alerts. Returns last N alerts with optional level/host filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of alerts to return", "default": 50},
                "level": {"type": "string", "description": "Filter by level (info/warn/error)", "default": ""},
                "host": {"type": "string", "description": "Filter by host", "default": ""},
                "source": {"type": "string", "description": "Filter by source agent", "default": ""},
                "since": {"type": "string", "description": "ISO timestamp or '24h', '7d'", "default": ""},
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
]


def _query(args: dict) -> str:
    sql = args.get("sql", "")
    params = args.get("params", [])
    try:
        conn = _get_conn(admin=False)
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall()
        cur.close()
        result = [dict(zip(cols, row)) for row in rows]
        return json.dumps({"row_count": len(result), "columns": cols, "rows": result}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _execute(args: dict) -> str:
    sql = args.get("sql", "")
    params = args.get("params", [])
    if not PGSQL_ADMIN_USER:
        return json.dumps({"error": "PGSQL_ADMIN_USER not configured, admin operations disabled"})
    try:
        conn = _get_conn(admin=True)
        cur = conn.cursor()
        cur.execute(sql, params)
        rowcount = cur.rowcount
        cur.close()
        return json.dumps({"affected_rows": rowcount})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _insert_alert(args: dict) -> str:
    try:
        conn = _get_conn(admin=True)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO alerts (source, level, host, service, message, action, result)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                args.get("source", ""),
                args.get("level", "info"),
                args.get("host", ""),
                args.get("service", ""),
                args.get("message", ""),
                args.get("action", ""),
                args.get("result", ""),
            ),
        )
        cur.close()
        return json.dumps({"status": "ok"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _get_alerts(args: dict) -> str:
    limit = args.get("limit", 50)
    level = args.get("level", "")
    host = args.get("host", "")
    source = args.get("source", "")
    since = args.get("since", "")
    try:
        conn = _get_conn(admin=False)
        cur = conn.cursor()
        where = []
        params = []
        if level:
            where.append("level = %s")
            params.append(level)
        if host:
            where.append("host = %s")
            params.append(host)
        if source:
            where.append("source = %s")
            params.append(source)
        if since:
            if since == "24h":
                where.append("ts >= NOW() - INTERVAL '24 hours'")
            elif since == "7d":
                where.append("ts >= NOW() - INTERVAL '7 days'")
            elif since == "30d":
                where.append("ts >= NOW() - INTERVAL '30 days'")
            else:
                where.append("ts >= %s")
                params.append(since)
        w = "WHERE " + " AND ".join(where) if where else ""
        sql = f"SELECT * FROM alerts {w} ORDER BY ts DESC LIMIT %s"
        cur.execute(sql, params + [limit])
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
        result = [dict(zip(cols, [str(c) if hasattr(c, 'isoformat') else c for c in row])) for row in rows]
        return json.dumps({"row_count": len(result), "rows": result}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _list_tables(args: dict) -> str:
    try:
        conn = _get_conn(admin=False)
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name, table_type FROM information_schema.tables
            WHERE table_schema = 'public' ORDER BY table_name
        """)
        rows = cur.fetchall()
        cur.close()
        lines = [f"  {r[0]:30s} {r[1]}" for r in rows]
        return "Tables:\n" + "\n".join(lines) if lines else "No tables found"
    except Exception as e:
        return json.dumps({"error": str(e)})


def _describe_table(args: dict) -> str:
    table = args.get("table", "")
    try:
        conn = _get_conn(admin=False)
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table,))
        rows = cur.fetchall()
        cur.close()
        lines = [f"  {r[0]:25s} {r[1]:20s} nullable={r[2]:5s} default={r[3] or '-'}" for r in rows]
        return f"Table: {table}\n" + "\n".join(lines) if lines else f"Table '{table}' not found"
    except Exception as e:
        return json.dumps({"error": str(e)})


TOOL_FUNCS = {
    "pgsql_query": _query,
    "pgsql_execute": _execute,
    "pgsql_insert_alert": _insert_alert,
    "pgsql_get_alerts": _get_alerts,
    "pgsql_list_tables": _list_tables,
    "pgsql_describe_table": _describe_table,
}

app = FastAPI(title="pgsql-mcp")

MCP_API_KEY = os.environ.get("MCP_API_KEY", "")


@app.middleware("http")
async def auth_middleware(request, call_next):
    if MCP_API_KEY:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {MCP_API_KEY}":
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int = 1
    method: str
    params: dict = {}


@app.on_event("startup")
async def startup():
    _init_schema()


@app.post("/mcp")
async def handle_mcp(req: MCPRequest):
    if req.method == "tools/list":
        return {"jsonrpc": "2.0", "result": {"tools": TOOLS}, "id": req.id}
    elif req.method == "tools/call":
        name = req.params.get("name", "")
        args = req.params.get("arguments", {})
        func = TOOL_FUNCS.get(name)
        if func:
            try:
                result = func(args)
                return {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": str(result)}]}, "id": req.id}
            except Exception as e:
                return {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": req.id}
        return {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Tool not found: {name}"}, "id": req.id}
    return {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Method not found: {req.method}"}, "id": req.id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PGSQL_MCP_PORT", 8020)))
