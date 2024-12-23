"""empty message

Revision ID: be296d260a4e
Revises: ebdd0637737e
Create Date: 2024-12-17 13:40:08.340593

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be296d260a4e'
down_revision: Union[str, None] = 'ebdd0637737e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('forest_area', sa.Column('region', sa.Text(), nullable=True))
    op.add_column('forest_area', sa.Column('area_ha', sa.Numeric(), nullable=True))
    op.add_column('forest_area', sa.Column('date', sa.Text(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('forest_area', 'date')
    op.drop_column('forest_area', 'area_ha')
    op.drop_column('forest_area', 'region')
    # ### end Alembic commands ###
