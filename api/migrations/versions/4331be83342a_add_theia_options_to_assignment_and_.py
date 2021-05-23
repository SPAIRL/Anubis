"""ADD theia options to assignment and course

Revision ID: 4331be83342a
Revises: d8b8114e003a
Create Date: 2021-04-27 14:19:24.005972

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "4331be83342a"
down_revision = "d8b8114e003a"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "assignment", sa.Column("theia_options", sa.JSON(), nullable=True)
    )
    op.add_column(
        "course", sa.Column("theia_default_image", sa.TEXT(), nullable=False)
    )
    op.add_column(
        "course", sa.Column("theia_default_options", sa.JSON(), nullable=True)
    )
    conn = op.get_bind()
    with conn.begin():
        conn.execute("update assignment set theia_options = '{}';")
        conn.execute("update course set theia_default_image = 'registry.digitalocean.com/anubis/theia-xv6';")
        conn.execute("update course set theia_default_options = '{}';")
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("course", "theia_default_options")
    op.drop_column("course", "theia_default_image")
    op.drop_column("assignment", "theia_options")
    # ### end Alembic commands ###
