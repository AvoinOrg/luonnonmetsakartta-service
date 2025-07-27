from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

used_db_types = []

IndexingStrategy = Literal["name_municipality", "id"]


class ColOptions(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    indexing_strategy: IndexingStrategy = Field(alias="indexingStrategy")
    id_col: str | None = Field(None, alias="idCol")
    name_col: str = Field(alias="nameCol")
    municipality_col: str = Field(alias="municipalityCol")
    region_col: str | None = Field(None, alias="regionCol")
    description_col: str | None = Field(None, alias="descriptionCol")
    area_col: str | None = Field(None, alias="areaCol")
