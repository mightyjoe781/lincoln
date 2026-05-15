"""fulltext search

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-15

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invoices", sa.Column("search_vector", postgresql.TSVECTOR, nullable=True))
    op.create_index(
        "ix_invoices_search_vector", "invoices", ["search_vector"], postgresql_using="gin"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION invoices_search_vector_trigger() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english', COALESCE(NEW.raw_text, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER invoices_search_vector_update
        BEFORE INSERT OR UPDATE ON invoices
        FOR EACH ROW EXECUTE FUNCTION invoices_search_vector_trigger();
    """)
    op.execute("UPDATE invoices SET search_vector = to_tsvector('english', COALESCE(raw_text, ''))")

    op.add_column("transactions", sa.Column("search_vector", postgresql.TSVECTOR, nullable=True))
    op.create_index(
        "ix_transactions_search_vector", "transactions", ["search_vector"], postgresql_using="gin"
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION transactions_search_vector_trigger() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english', COALESCE(NEW.description, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER transactions_search_vector_update
        BEFORE INSERT OR UPDATE ON transactions
        FOR EACH ROW EXECUTE FUNCTION transactions_search_vector_trigger();
    """)
    op.execute(
        "UPDATE transactions SET search_vector = to_tsvector('english', COALESCE(description, ''))"
    )


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS transactions_search_vector_update ON transactions")
    op.execute("DROP FUNCTION IF EXISTS transactions_search_vector_trigger")
    op.drop_index("ix_transactions_search_vector", table_name="transactions")
    op.drop_column("transactions", "search_vector")
    op.execute("DROP TRIGGER IF EXISTS invoices_search_vector_update ON invoices")
    op.execute("DROP FUNCTION IF EXISTS invoices_search_vector_trigger")
    op.drop_index("ix_invoices_search_vector", table_name="invoices")
    op.drop_column("invoices", "search_vector")
