-- PostgreSQL ilk kurulum: database + user + yetkiler
-- KULLANIM: psql -U postgres -f scripts/init_pgsql.sql
-- NOT: DB/users zaten varsa hata verir, sorunsuz devam etmek icin
--       once su komutu calistir:
--       psql -U postgres -d mcp_platform -f scripts/grant_schema.sql

CREATE DATABASE mcp_platform;

CREATE USER mcp_user WITH PASSWORD 'mcp_pass';
GRANT CONNECT ON DATABASE mcp_platform TO mcp_user;

CREATE USER mcp_admin WITH PASSWORD 'admin_pass';
GRANT CONNECT ON DATABASE mcp_platform TO mcp_admin;
GRANT ALL PRIVILEGES ON DATABASE mcp_platform TO mcp_admin;
