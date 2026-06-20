from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

from registry.api import router as registry_router
from agt_gateway.gateway import router as gateway_router, state as gateway_state

app = FastAPI(title="MCP Governance Platform", version="0.1.0")

app.include_router(registry_router)
app.include_router(gateway_router)


@app.get("/health")
async def root_health():
    return {
        "message": "MCP Governance Platform",
        "status": "running",
        "services": ["AGT Gateway", "MCP Registry", "Control Panel"],
        "gateway_mode": "real",
        "policy": gateway_state.policy.name,
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    with open("templates/index.html") as f:
        return HTMLResponse(f.read())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
