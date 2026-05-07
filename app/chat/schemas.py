

from pydantic import EmailStr, ConfigDict, BaseModel
from datetime import datetime


# first schemas for sessions people

class SessionCreate(BaseModel):
    title: str = "New Chat"

class SessionResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    created_at: datetime



# Now is the schemas for Messages


class MessageCreate(BaseModel):
    content: str

class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

