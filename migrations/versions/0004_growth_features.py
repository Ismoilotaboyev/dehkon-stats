"""Scheduling, photos, post types, insights, staff names

Revision ID: 0004
Revises: 0003
"""
import json
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

# Starter post types for Dehqon Dorixona (style/structure only; no facts are invented).
DORIXONA_TEMPLATES = [
    {'key': 'hamshira', 'name': '🩺 Hamshira xizmati',
     'prompt': "Uyga hamshira chaqirish xizmati haqida. Ishonch va g'amxo'rlik ohangi. CTA: qo'ng'iroq qiling yoki Direct'ga yozing."},
    {'key': 'aksiya', 'name': '🏷 Aksiya',
     'prompt': "Aksiya/chegirma posti. Faqat videoda aniq aytilgan chegirma, narx va muddatni yoz; o'zingdan raqam qo'shma. Shoshilishga undovchi qisqa CTA."},
    {'key': 'yangi', 'name': '🆕 Yangi mahsulot',
     'prompt': "Dorixonaga yangi kelgan mahsulot. Nomi va videoda aytilgan xususiyatlari. Davolash va'dasi yozma. CTA: dorixonaga keling yoki buyurtma bering."},
    {'key': 'maslahat', 'name': '💡 Maslahat',
     'prompt': "Foydali sog'liq maslahati, ma'rifiy ohang. Videodagi maslahatni qisqa qilib ber, oxirida 'shifokor bilan maslahatlashing' degan eslatma."},
]


def upgrade():
    op.add_column('brands', sa.Column('publish_slots', sa.String(200), nullable=False, server_default=''))
    op.add_column('brands', sa.Column('templates', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('videos', sa.Column('media_kind', sa.String(10), nullable=False, server_default='video'))
    op.add_column('videos', sa.Column('post_type', sa.String(40), nullable=False, server_default=''))
    op.add_column('videos', sa.Column('sender_name', sa.String(200), nullable=False, server_default=''))
    op.add_column('videos', sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('videos', sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column('publications', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('publications', sa.Column('checks_done', sa.Integer(), nullable=False, server_default='0'))
    op.create_table('post_metrics',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('publication_id', sa.String(length=36), nullable=False),
        sa.Column('hours', sa.Integer(), nullable=False),
        sa.Column('views', sa.Integer(), nullable=False),
        sa.Column('reach', sa.Integer(), nullable=False),
        sa.Column('likes', sa.Integer(), nullable=False),
        sa.Column('comments', sa.Integer(), nullable=False),
        sa.Column('saves', sa.Integer(), nullable=False),
        sa.Column('shares', sa.Integer(), nullable=False),
        sa.Column('permalink', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['publication_id'], ['publications.id']),
        sa.PrimaryKeyConstraint('id'))
    # Publications that were published before this migration: no timestamp -> skip their insight checks.
    op.execute("UPDATE publications SET checks_done = 2 WHERE status = 'published'")
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE brands SET templates = :t WHERE slug = 'dehkon-dorixona'"),
                 {'t': json.dumps(DORIXONA_TEMPLATES, ensure_ascii=False)})


def downgrade():
    op.drop_table('post_metrics')
    for table, col in [('publications', 'checks_done'), ('publications', 'published_at'), ('videos', 'created_at'),
                       ('videos', 'scheduled_at'), ('videos', 'sender_name'), ('videos', 'post_type'),
                       ('videos', 'media_kind'), ('brands', 'templates'), ('brands', 'publish_slots')]:
        op.drop_column(table, col)
