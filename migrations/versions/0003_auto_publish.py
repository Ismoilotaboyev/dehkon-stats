"""brands.auto_publish (videos without an AI flag skip approval); on for Dehqon Dorixona

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('brands', sa.Column('auto_publish', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE brands SET auto_publish = TRUE WHERE slug = 'dehkon-dorixona'")


def downgrade():
    op.drop_column('brands', 'auto_publish')
