"""CHG theia options columns

Revision ID: 587921276e67
Revises: 1a6dbe1012b5
Create Date: 2021-08-17 14:30:42.820235

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "587921276e67"
down_revision = "1a6dbe1012b5"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("theia_session", sa.Column("resources", sa.JSON(), nullable=True))
    op.add_column(
        "theia_session",
        sa.Column("network_policy", sa.String(length=128), nullable=True),
    )
    op.add_column("theia_session", sa.Column("autosave", sa.Boolean(), nullable=True))
    op.add_column(
        "theia_session", sa.Column("credentials", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "theia_session", sa.Column("persistent_storage", sa.Boolean(), nullable=True)
    )
    op.drop_column("theia_session", "options")
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "theia_session",
        sa.Column(
            "options",
            mysql.LONGTEXT(charset="utf8mb4", collation="utf8mb4_bin"),
            nullable=False,
        ),
    )
    op.drop_column("theia_session", "credentials")
    op.drop_column("theia_session", "autosave")
    op.drop_column("theia_session", "network_policy")
    op.drop_column("theia_session", "resources")
    op.drop_column("theia_session", "persistent_storage")
    # ### end Alembic commands ###
