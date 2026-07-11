# somewhere near your demo, e.g. itc/intelligence/schemas.py
from pydantic import BaseModel


class VerdictExplanation(BaseModel):
    explanation: str
