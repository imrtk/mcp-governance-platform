import sys, os, subprocess, shlex, re
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="shell-mcp-http")

MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

@app.middleware("http")
async def auth_middleware(request, call_next):
    if MCP_API_KEY:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {MCP_API_KEY}":
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)

ALLOWLIST = {
    "ls", "cat", "head", "tail", "wc", "nl", "od", "xxd",
    "pwd", "tree", "du", "df", "stat", "realpath", "readlink", "dirname", "basename",
    "echo", "grep", "sort", "uniq", "cut", "tr", "diff", "comm", "tee",
    "fold", "pr", "expand", "unexpand", "fmt",
    "file", "which", "type",
    "whoami", "id", "who", "w", "last", "date", "cal", "uptime", "uname",
    "hostname", "env", "printenv", "nproc", "free", "lscpu", "lsblk",
    "lsusb", "lspci", "lshw",
    "ps", "top",
    "ss", "ip", "hostname",
    "tar", "gzcat", "zcat", "bzcat", "xzcat",
}

def is_command_allowed(full_command: str) -> tuple[bool, str]:
    cmd_stripped = full_command.strip()
    if not cmd_stripped:
        return False, "Empty command"
    forbidden = re.compile(r'[;&`$\n\\!(){}]')
    if forbidden.search(cmd_stripped):
        return False, "Shell metacharacters not allowed"
    if re.search(r'(>|>>)\s*(/dev/|/proc/|/sys/)', cmd_stripped):
        return False, "Redirect to system paths blocked"
    for segment in cmd_stripped.split("|"):
        segment = segment.strip()
        if not segment:
            continue
        try:
            parts = shlex.split(segment)
        except ValueError:
            return False, f"Invalid shell quoting"
        if not parts:
            continue
        base_cmd = os.path.basename(parts[0])
        if base_cmd not in ALLOWLIST:
            return False, f"Command '{base_cmd}' not in allowlist"
    return True, ""

def run_shell(command: str, timeout: int = 30):
    allowed, reason = is_command_allowed(command)
    if not allowed:
        return {"error": f"Blocked: {reason}"}
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}

class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int = 1
    method: str
    params: dict = {}

@app.post("/mcp")
async def handle_mcp(req: MCPRequest):
    if req.method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "result": {
                "tools": [
                    {
                        "name": "run_shell",
                        "description": "Run a shell command securely using an allowlist approach",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Shell command to run"},
                                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30}
                            },
                            "required": ["command"]
                        }
                    }
                ]
            },
            "id": req.id
        }
    elif req.method == "tools/call":
        name = req.params.get("name", "")
        args = req.params.get("arguments", {})
        if name == "run_shell":
            result = run_shell(**args)
            return {
                "jsonrpc": "2.0",
                "result": {
                    "content": [{"type": "text", "text": str(result)}]
                },
                "id": req.id
            }
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Tool not found: {name}"},
            "id": req.id
        }
    else:
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Method not found: {req.method}"},
            "id": req.id
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("MCP_PORT", 8002)))
