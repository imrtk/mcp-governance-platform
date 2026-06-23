-- Schema yetkileri (PostgreSQL 15+ icin gerekli)
-- KULLANIM: psql -U postgres -d mcp_platform -f scripts/grant_schema.sql

GRANT USAGE ON SCHEMA public TO mcp_user;
GRANT USAGE ON SCHEMA public TO mcp_admin;
GRANT CREATE ON SCHEMA public TO mcp_admin;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_user;
