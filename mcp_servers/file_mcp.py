from fastapi import FastAPI
from pydantic import BaseModel
from pathlib import Path
import uvicorn

app = FastAPI(title="file-mcp", version="0.1.0")


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict = {}
    id: int = 1


class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: dict = {}
    id: int


@app.post("/mcp")
async def mcp_handler(req: MCPRequest):
    if req.method == "tools/list":
        return MCPResponse(result={
            "tools": [
                {"name": "list_dir", "description": "List directory contents", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Directory path", "default": "."}}}},
                {"name": "read_file", "description": "Read file contents", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "File path"}}, "required": ["path"]}},
                {"name": "write_file", "description": "Write content to file", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "File path"}, "content": {"type": "string", "description": "Content to write"}}, "required": ["path", "content"]}},
                {"name": "search_files", "description": "Search files by glob pattern", "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Glob pattern"}, "path": {"type": "string", "description": "Base directory", "default": "."}}, "required": ["pattern"]}},
                {"name": "grep", "description": "Search text in files", "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Text to search"}, "path": {"type": "string", "description": "Base directory", "default": "."}}, "required": ["pattern"]}},
            ]
        }, id=req.id)

    if req.method == "tools/call":
        tool_name = req.params.get("name")
        args = req.params.get("arguments", {})

        try:
            if tool_name == "list_dir":
                path = args.get("path", ".")
                resolved = Path(path).expanduser().resolve()
                if not resolved.exists():
                    return _error(req.id, f"path does not exist: {path}")
                if not resolved.is_dir():
                    return _error(req.id, f"not a directory: {path}")
                entries = [f"{e.name}{'/' if e.is_dir() else ''}" for e in sorted(resolved.iterdir())]
                return _result(req.id, {"content": [{"type": "text", "text": "\n".join(entries)}]})

            if tool_name == "read_file":
                path = args["path"]
                resolved = Path(path).expanduser().resolve()
                if not resolved.exists():
                    return _error(req.id, f"file not found: {path}")
                if not resolved.is_file():
                    return _error(req.id, f"not a file: {path}")
                text = resolved.read_text(encoding="utf-8")
                return _result(req.id, {"content": [{"type": "text", "text": text}]})

            if tool_name == "write_file":
                path = args["path"]
                content = args["content"]
                resolved = Path(path).expanduser().resolve()
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_text(content, encoding="utf-8")
                return _result(req.id, {"content": [{"type": "text", "text": f"Written {len(content)} bytes to {resolved}"}]})

            if tool_name == "search_files":
                pattern = args["pattern"]
                path = args.get("path", ".")
                resolved = Path(path).expanduser().resolve()
                matches = list(resolved.rglob(pattern))
                if not matches:
                    return _result(req.id, {"content": [{"type": "text", "text": f"No matches for '{pattern}'"}]})
                lines = [str(m.relative_to(resolved)) for m in matches[:50]]
                return _result(req.id, {"content": [{"type": "text", "text": "\n".join(lines)}]})

            if tool_name == "grep":
                pattern = args["pattern"]
                path = args.get("path", ".")
                resolved = Path(path).expanduser().resolve()
                results = []
                for f in resolved.rglob("*"):
                    if f.is_file() and f.suffix in {".py", ".txt", ".md", ".json", ".yaml", ".toml", ".log"}:
                        try:
                            for i, line in enumerate(f.read_text().splitlines(), 1):
                                if pattern in line:
                                    results.append(f"{f.relative_to(resolved)}:{i}: {line[:200]}")
                        except Exception:
                            pass
                if not results:
                    return _result(req.id, {"content": [{"type": "text", "text": f"No matches for '{pattern}'"}]})
                return _result(req.id, {"content": [{"type": "text", "text": "\n".join(results[:50])}]})

            return _error(req.id, f"unknown tool: {tool_name}")

        except Exception as e:
            return _error(req.id, str(e))

    return _error(req.id, f"unknown method: {req.method}")


def _result(req_id: int, data: dict):
    return {"jsonrpc": "2.0", "result": data, "id": req_id}


def _error(req_id: int, msg: str):
    return {"jsonrpc": "2.0", "error": {"code": -32000, "message": msg}, "id": req_id}


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "file-mcp"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
