"""CHG rename sequence to pool

Revision ID: bf3ae1de1d12
Revises: 3ed4da84667e
Create Date: 2021-05-19 20:20:32.269570

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "bf3ae1de1d12"
down_revision = "3ed4da84667e"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "assignment_question", "sequence", new_column_name="pool", type_=sa.Integer()
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "assignment_question", "pool", new_column_name="sequence", type_=sa.Integer()
    )
    # ### end Alembic commands ###
