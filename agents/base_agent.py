import os, httpx, json, threading, time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
from fastapi import FastAPI
from pydantic import BaseModel

REGISTRY_URL = os.getenv("REGISTRY_URL", "http://localhost:8080")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
POLL_INTERVAL = float(os.getenv("AGENT_POLL_INTERVAL", "2.0"))


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int = 1
    method: str
    params: dict = {}


class BaseAgent:
    def __init__(self, name: str, description: str, tools: list[dict],
                 tool_funcs: dict, port: int, platform: str = "local"):
        self.name = name
        self.description = description
        self.tools = tools
        self.tool_funcs = tool_funcs
        self.port = port
        self.platform = platform

        self.app = FastAPI(title=name)
        self._register_routes()

    def _register_routes(self):
        @self.app.post("/mcp")
        async def handle_mcp(req: MCPRequest):
            if req.method == "tools/list":
                return {"jsonrpc": "2.0", "result": {"tools": self.tools}, "id": req.id}
            elif req.method == "tools/call":
                name = req.params.get("name", "")
                args = req.params.get("arguments", {})
                func = self.tool_funcs.get(name)
                if func:
                    try:
                        result = func(args)
                        return {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": str(result)}]}, "id": req.id}
                    except Exception as e:
                        return {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": req.id}
                return {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Tool not found: {name}"}, "id": req.id}
            return {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Method not found: {req.method}"}, "id": req.id}

        @self.app.get("/health")
        async def health():
            return {"agent": self.name, "status": "running", "tools": len(self.tools)}

    def register(self):
        try:
            payload = {
                "name": self.name,
                "description": self.description,
                "url": f"http://localhost:{self.port}",
                "status": "running",
                "platform": self.platform,
                "capabilities": [t["name"] for t in self.tools],
            }
            resp = httpx.post(f"{REGISTRY_URL}/api/registry/servers", json=payload, timeout=5)
            if resp.status_code == 409:
                print(f"[{self.name}] Already registered")
                return
            resp.raise_for_status()
            print(f"[{self.name}] Registered in registry")
        except Exception as e:
            print(f"[{self.name}] Register warning: {e}")

    def _call_gateway(self, tool_name: str, params: dict, mcp_name: str) -> str:
        try:
            resp = httpx.post(
                f"{GATEWAY_URL}/api/gateway/govern/{mcp_name}",
                json={"agent_id": self.name, "tool_name": tool_name, "params": params},
                timeout=30,
            )
            data = resp.json()
            if not data.get("allowed"):
                return f"[BLOCKED] {data.get('reason', 'policy denied')}"
            result = data.get("result", {})
            contents = result.get("result", {}).get("content", [])
            return "\n".join(c.get("text", "") for c in contents)
        except Exception as e:
            return f"[ERROR] {e}"

    def _poll_messages(self):
        while True:
            try:
                resp = httpx.get(f"{GATEWAY_URL}/api/gateway/agent/messages/{self.name}", timeout=10)
                if resp.status_code == 200:
                    for msg in resp.json().get("messages", []):
                        self._handle_message(msg)
            except Exception:
                pass
            time.sleep(POLL_INTERVAL)

    def _handle_message(self, msg: dict):
        pass

    def start_polling(self):
        t = threading.Thread(target=self._poll_messages, daemon=True)
        t.start()
        print(f"[{self.name}] Message polling started")

    def ask_agent(self, agent_name: str, tool_name: str, params: dict) -> str:
        return self._call_gateway(tool_name, params, agent_name)

    def run(self):
        import uvicorn
        self.register()
        self.start_polling()
        print(f"[{self.name}] Starting on port {self.port}")
        uvicorn.run(self.app, host="0.0.0.0", port=self.port)
