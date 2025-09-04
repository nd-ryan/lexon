from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_cases_table(engine: Engine) -> None:
    ddl = text(
        """
        CREATE TABLE IF NOT EXISTS cases (
          id UUID PRIMARY KEY,
          filename TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          extracted JSONB,
          schema_version TEXT,
          revisions JSONB NOT NULL DEFAULT '[]'::jsonb,
          meta JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_cases_updated_at ON cases (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cases_status ON cases (status);
        """
    )
    with engine.begin() as conn:
        conn.execute(ddl)


