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
          kg_extracted JSONB,
          schema_version TEXT,
          meta JSONB NOT NULL DEFAULT '{}'::jsonb,
          original_author_id TEXT,
          file_key TEXT,
          kg_submitted_by TEXT,
          kg_submitted_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_cases_updated_at ON cases (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cases_status ON cases (status);
        
        -- Add columns if they don't exist (for existing databases)
        DO $$ 
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'original_author_id') THEN
                ALTER TABLE cases ADD COLUMN original_author_id TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'file_key') THEN
                ALTER TABLE cases ADD COLUMN file_key TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'kg_submitted_by') THEN
                ALTER TABLE cases ADD COLUMN kg_submitted_by TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'kg_submitted_at') THEN
                ALTER TABLE cases ADD COLUMN kg_submitted_at TIMESTAMPTZ;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'kg_extracted') THEN
                ALTER TABLE cases ADD COLUMN kg_extracted JSONB;
            END IF;
        END $$;
        """
    )
    with engine.begin() as conn:
        conn.execute(ddl)


def ensure_graph_events_table(engine: Engine) -> None:
    """Create the graph_events table for audit logging."""
    ddl = text(
        """
        CREATE TABLE IF NOT EXISTS graph_events (
          id UUID PRIMARY KEY,
          case_id UUID NOT NULL,
          entity_type TEXT NOT NULL,
          entity_id TEXT NOT NULL,
          entity_label TEXT NOT NULL,
          action TEXT NOT NULL,
          user_id TEXT NOT NULL,
          content_hash TEXT,
          property_changes JSONB,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_graph_events_case_id ON graph_events (case_id);
        CREATE INDEX IF NOT EXISTS idx_graph_events_entity_id ON graph_events (entity_id);
        CREATE INDEX IF NOT EXISTS idx_graph_events_user_id ON graph_events (user_id);
        CREATE INDEX IF NOT EXISTS idx_graph_events_created_at ON graph_events (created_at DESC);
        """
    )
    with engine.begin() as conn:
        conn.execute(ddl)


def ensure_case_comparisons_table(engine: Engine) -> None:
    """Create the case_comparisons table for storing comparison results."""
    ddl = text(
        """
        CREATE TABLE IF NOT EXISTS case_comparisons (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          case_id UUID NOT NULL UNIQUE REFERENCES cases(id) ON DELETE CASCADE,
          compared_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          postgres_updated_at TIMESTAMPTZ,
          kg_submitted_at TIMESTAMPTZ,
          all_match BOOLEAN NOT NULL,
          nodes_differ_count INTEGER DEFAULT 0,
          edges_differ_count INTEGER DEFAULT 0,
          embeddings_missing_count INTEGER DEFAULT 0,
          details JSONB
        );

        CREATE INDEX IF NOT EXISTS idx_case_comparisons_case_id ON case_comparisons(case_id);
        CREATE INDEX IF NOT EXISTS idx_case_comparisons_all_match ON case_comparisons(all_match);
        """
    )
    with engine.begin() as conn:
        conn.execute(ddl)


def ensure_all_tables(engine: Engine) -> None:
    """Ensure all required tables exist."""
    ensure_cases_table(engine)
    ensure_graph_events_table(engine)
    ensure_case_comparisons_table(engine)


