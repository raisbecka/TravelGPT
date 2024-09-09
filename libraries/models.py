from typing import List, Optional

from langchain.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field, validator


class Country(BaseModel):
    """Information about a country."""
    name: str = Field(..., description="Name of the country")


class Countries(BaseModel):
    """A list of countries."""
    people: List[Country]