"""empty message

Revision ID: 9d2226b17311
Revises: ddc489b71091
Create Date: 2025-03-28 12:57:55.174713

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

# revision identifiers, used by Alembic.
revision: str = "9d2226b17311"
down_revision: Union[str, None] = "ddc489b71091"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.execute("""
    ALTER TABLE forest_area ADD COLUMN centroid GEOMETRY(POINT, 3067) 
    GENERATED ALWAYS AS (ST_Centroid(geometry)) STORED
    """)
    op.create_index(
        "idx_forest_area_centroid",
        "forest_area",
        ["centroid"],
        unique=False,
        postgresql_using="gist",
    )

    # Update all existing rows
    # op.execute(
    #     "UPDATE forest_area SET centroid = ST_Centroid(geometry) WHERE geometry IS NOT NULL"
    # )

    # # Create function for trigger
    # op.execute("""
    # CREATE OR REPLACE FUNCTION update_forest_area_centroid()
    # RETURNS TRIGGER AS $$
    # BEGIN
    #     NEW.centroid = ST_Centroid(NEW.geometry);
    #     RETURN NEW;
    # END;
    # $$ LANGUAGE plpgsql;
    # """)

    # # Create trigger
    # op.execute("""
    # CREATE TRIGGER forest_area_centroid_trigger
    # BEFORE INSERT OR UPDATE OF geometry ON forest_area
    # FOR EACH ROW
    # WHEN (NEW.geometry IS NOT NULL)
    # EXECUTE FUNCTION update_forest_area_centroid();
    # """)
    # ### end Alembic commands ###


def downgrade() -> None:
    # op.execute("DROP TRIGGER IF EXISTS forest_area_centroid_trigger ON forest_area")
    # op.execute("DROP FUNCTION IF EXISTS update_forest_area_centroid()")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        "idx_forest_area_centroid", table_name="forest_area", postgresql_using="gist"
    )
    op.drop_column("forest_area", "centroid")
    # ### end Alembic commands ###
