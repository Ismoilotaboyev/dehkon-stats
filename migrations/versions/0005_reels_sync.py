"""Instagram Reels -> YouTube Shorts sync (on for Dehqon Dorixona)

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('brands', sa.Column('reels_sync', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('brands', sa.Column('reels_sync_slots', sa.String(200), nullable=False,
                                      server_default='10:00, 14:00, 18:00, 21:00'))
    op.create_table('ig_sync',
        sa.Column('ig_media_id', sa.String(length=64), nullable=False),
        sa.Column('brand_slug', sa.String(length=120), nullable=False),
        sa.Column('permalink', sa.Text(), nullable=False),
        sa.Column('caption', sa.Text(), nullable=False),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('shared_to_feed', sa.Boolean(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('youtube_id', sa.String(length=64), nullable=False),
        sa.Column('details', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('ig_media_id'))
    op.execute("UPDATE brands SET reels_sync = TRUE WHERE slug = 'dehkon-dorixona'")


def downgrade():
    op.drop_table('ig_sync')
    op.drop_column('brands', 'reels_sync_slots')
    op.drop_column('brands', 'reels_sync')
