"""Fix column type

Revision ID: 2bb22583c94a
Revises: a4d9e88420ae
Create Date: 2025-08-17 13:56:09.328463

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2bb22583c94a'
down_revision: Union[str, None] = 'a4d9e88420ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def get_view_definitions(conn):
    """
    Fetches the definitions for all dynamically created GeoServer views.
    """
    try:
        layers = conn.execute(sa.text("SELECT id FROM forest_layer")).fetchall()
    except sa.exc.ProgrammingError as e:
        # If the table doesn't exist yet, there are no views to worry about.
        if 'relation "forest_layer" does not exist' in str(e):
            return []
        raise
        
    view_defs = []
    for layer in layers:
        layer_id = str(layer[0])
        sanitized_id = layer_id.replace("-", "")
        
        area_view_name = f"forest_areas_{sanitized_id}"
        centroid_view_name = f"forest_areas_{sanitized_id}_centroid"

        area_sql = f"""
            CREATE OR REPLACE VIEW "{area_view_name}" AS
            SELECT 
                id,
                name,
                geometry
            FROM forest_area 
            WHERE layer_id::text = '{layer_id}'
        """

        centroid_sql = f"""
            CREATE OR REPLACE VIEW "{centroid_view_name}" AS
            SELECT
                fa.id,
                fa.name,
                fa.created_ts,
                fa.updated_ts,
                fa.description,
                fa.municipality,
                fa.region,
                fa.area_ha,
                fa.date,
                fa.centroid AS geometry,
                jsonb_agg(p.bucket_url) FILTER (WHERE p.id IS NOT NULL) as pictures
            FROM
                forest_area fa
            LEFT JOIN
                picture p ON fa.id = p.forest_area_id
            WHERE
                fa.layer_id::text = '{layer_id}'
                AND fa.centroid IS NOT NULL
            GROUP BY
                fa.id
        """
        view_defs.append({'name': area_view_name, 'sql': area_sql})
        view_defs.append({'name': centroid_view_name, 'sql': centroid_sql})
    return view_defs


def upgrade() -> None:
    conn = op.get_bind()
    
    # 1. Get existing view definitions
    view_defs = get_view_definitions(conn)
    
    # 2. Drop the views
    for view in view_defs:
        op.execute(f'DROP VIEW IF EXISTS "{view["name"]}" CASCADE')

    # 3. Alter the column
    op.alter_column('forest_area', 'description',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               type_=sa.Text(),
               existing_nullable=True,
               postgresql_using='description::text')

    # 4. Recreate the views
    for view in view_defs:
        op.execute(view['sql'])


def downgrade() -> None:
    conn = op.get_bind()

    # 1. Get existing view definitions
    view_defs = get_view_definitions(conn)

    # 2. Drop the views
    for view in view_defs:
        op.execute(f'DROP VIEW IF EXISTS "{view["name"]}" CASCADE')

    # 3. Alter the column back
    op.alter_column('forest_area', 'description',
               existing_type=sa.Text(),
               type_=postgresql.JSONB(astext_type=sa.Text()),
               existing_nullable=True,
               postgresql_using='to_jsonb(description)')

    # 4. Recreate the views
    for view in view_defs:
        op.execute(view['sql'])
