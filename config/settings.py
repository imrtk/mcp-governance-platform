from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "MCP Governance Platform"
    VERSION: str = "0.1.0"
    DEBUG: bool = True
    DATABASE_URL: str = "sqlite+aiosqlite:///./database/mcp_governance.db"
    AGT_POLICY_PATH: str = "policies/default-policy.yaml"
    SECRET_KEY: str = "super-secret-key-change-in-production"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
