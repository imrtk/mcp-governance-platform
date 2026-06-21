from fastapi import FastAPI

from registry.api import router as registry_router
from mcp_governance.gateway.routes.govern import router as govern_router
from mcp_governance.gateway.routes.policy import router as policy_router
from mcp_governance.gateway.routes.audit import router as audit_router
from mcp_governance.gateway.routes.agents import router as agents_router
from mcp_governance.gateway.routes.monitor import router as monitor_router
from mcp_governance.gateway.routes.dashboard import router as dashboard_router
from mcp_governance.policy.engine import state


def create_app() -> FastAPI:
    app = FastAPI(title="MCP Governance Platform", version="0.1.0")

    app.include_router(registry_router)
    app.include_router(govern_router, prefix="/api/gateway")
    app.include_router(policy_router, prefix="/api/gateway")
    app.include_router(audit_router, prefix="/api/gateway")
    app.include_router(agents_router, prefix="/api/gateway")
    app.include_router(monitor_router, prefix="/api/gateway")
    app.include_router(dashboard_router)

    @app.get("/health")
    async def root_health():
        return {
            "message": "MCP Governance Platform",
            "status": "running",
            "services": ["AGT Gateway", "MCP Registry", "Control Panel"],
            "gateway_mode": "real",
            "policy": state.policy.name,
        }

    return app
