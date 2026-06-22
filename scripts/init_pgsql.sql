-- PostgreSQL ilk kurulum: database + user + yetkiler
-- psql -U postgres -f scripts/init_pgsql.sql

CREATE DATABASE mcp_platform;

CREATE USER mcp_user WITH PASSWORD 'mcp_pass';
GRANT CONNECT ON DATABASE mcp_platform TO mcp_user;

CREATE USER mcp_admin WITH PASSWORD 'admin_pass';
GRANT CONNECT ON DATABASE mcp_platform TO mcp_admin;
GRANT ALL PRIVILEGES ON DATABASE mcp_platform TO mcp_admin;
