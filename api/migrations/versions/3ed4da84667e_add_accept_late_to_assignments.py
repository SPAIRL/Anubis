"""ADD accept_late to assignments

Revision ID: 3ed4da84667e
Revises: 2324a3537ff3
Create Date: 2021-05-19 20:16:16.729701

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3ed4da84667e"
down_revision = "2324a3537ff3"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("assignment", sa.Column("accept_late", sa.Boolean(), nullable=True))
    conn = op.get_bind()
    with conn.begin():
        conn.execute("update assignment set accept_late = 1;")
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("assignment", "accept_late")
    # ### end Alembic commands ###
