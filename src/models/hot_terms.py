from pydantic import BaseModel, Field
from typing import Optional, List

class HotTermResponse(BaseModel):
    id: str
    term: str
    category: str
    weight: float
    variants: List[str]
    source: Optional[str]
    created_at: int

class SuggestTermRequest(BaseModel):
    term: str = Field(..., min_length=1, max_length=100)
    source: Optional[str] = Field(None, max_length=200)

class ClassifyTermRequest(BaseModel):
    term: str = Field(..., min_length=1, max_length=100)
    source: Optional[str] = Field(None, max_length=200)
