"""baseline backend tables.

Revision ID: 0001_baseline_backend_tables
Revises: 
Create Date: 2026-01-07
"""

from alembic import op

# Alembic revision identifiers.
revision = "0001_baseline_backend_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backend tables are expected to live in the `app` schema (or POSTGRES_SCHEMA).
    # This migration is safe for new databases. For existing databases, prefer:
    #   alembic stamp head
    # after you have moved tables into the correct schema.

    op.execute("CREATE SCHEMA IF NOT EXISTS app;")

    # Needed for gen_random_uuid() defaults (commonly enabled already).
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

    # cases
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.cases (
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

        CREATE INDEX IF NOT EXISTS idx_cases_updated_at ON app.cases (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cases_status ON app.cases (status);
        """
    )

    # graph_events
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.graph_events (
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

        CREATE INDEX IF NOT EXISTS idx_graph_events_case_id ON app.graph_events (case_id);
        CREATE INDEX IF NOT EXISTS idx_graph_events_entity_id ON app.graph_events (entity_id);
        CREATE INDEX IF NOT EXISTS idx_graph_events_user_id ON app.graph_events (user_id);
        CREATE INDEX IF NOT EXISTS idx_graph_events_created_at ON app.graph_events (created_at DESC);
        """
    )

    # case_comparisons
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app.case_comparisons (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          case_id UUID NOT NULL UNIQUE REFERENCES app.cases(id) ON DELETE CASCADE,
          compared_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          postgres_updated_at TIMESTAMPTZ,
          kg_submitted_at TIMESTAMPTZ,
          all_match BOOLEAN NOT NULL,
          nodes_differ_count INTEGER DEFAULT 0,
          edges_differ_count INTEGER DEFAULT 0,
          embeddings_missing_count INTEGER DEFAULT 0,
          details JSONB,
          needs_completion BOOLEAN DEFAULT FALSE,
          required_missing_count INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_case_comparisons_case_id ON app.case_comparisons(case_id);
        CREATE INDEX IF NOT EXISTS idx_case_comparisons_all_match ON app.case_comparisons(all_match);
        CREATE INDEX IF NOT EXISTS idx_case_comparisons_needs_completion ON app.case_comparisons(needs_completion);
        """
    )


def downgrade() -> None:
    # Downgrades are intentionally conservative; avoiding DROP TABLE reduces risk.
    # If you truly need to roll back, do so manually with extreme care.
    pass

