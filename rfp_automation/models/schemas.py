from pydantic import BaseModel

class Requirement(BaseModel):
    id: str
    text: str
    category: str
    mandatory: bool
