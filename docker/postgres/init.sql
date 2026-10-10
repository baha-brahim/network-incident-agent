-- Runs once, on first start of an empty data volume (as the `incident` superuser,
-- connected to the `incident_agent` database).

CREATE EXTENSION IF NOT EXISTS vector;

-- Read-only role for the agent's guarded SQL tool (M4).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_ro') THEN
        CREATE ROLE agent_ro LOGIN PASSWORD 'agent_ro';
    END IF;
END
$$;

ALTER ROLE agent_ro SET default_transaction_read_only = on;

GRANT CONNECT ON DATABASE incident_agent TO agent_ro;
GRANT USAGE ON SCHEMA public TO agent_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_ro;
-- Tables created later by `incident` (Alembic migrations) are readable too.
ALTER DEFAULT PRIVILEGES FOR ROLE incident IN SCHEMA public GRANT SELECT ON TABLES TO agent_ro;
