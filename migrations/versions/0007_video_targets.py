"""Per-video publish targets chosen by the sender

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('videos', sa.Column('targets', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('videos', 'targets')
