"""Re-post own Reels as Trial Reels on the same account

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('brands', sa.Column('trial_repost', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('brands', sa.Column('trial_repost_slots', sa.String(200), nullable=False,
                                      server_default='09:00, 11:00, 13:00, 15:00, 18:00, 21:00'))
    op.add_column('brands', sa.Column('trial_repost_paused_until', sa.DateTime(timezone=True), nullable=True))
    op.create_table('trial_repost',
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


def downgrade():
    op.drop_table('trial_repost')
    for col in ('trial_repost_paused_until', 'trial_repost_slots', 'trial_repost'):
        op.drop_column('brands', col)
