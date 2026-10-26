"""Dehqon Dorixona: phone number for the caption's last line

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

PHONE = '55 588 60 60'
LINE = f' Telefon raqami (captionning oxirgi qatori): 📞 {PHONE}'


def upgrade():
    conn = op.get_bind()
    row = conn.execute(sa.text("SELECT ai_prompt FROM brands WHERE slug='dehkon-dorixona'")).first()
    if row is not None and PHONE not in (row[0] or ''):
        conn.execute(sa.text("UPDATE brands SET ai_prompt=:p WHERE slug='dehkon-dorixona'"),
                     {'p': (row[0] or '') + LINE})


def downgrade():
    pass
