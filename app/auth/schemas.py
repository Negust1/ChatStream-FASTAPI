
from pydantic import BaseModel, EmailStr, ConfigDict
from datetime import datetime



class UserCreated(BaseModel):

    email: EmailStr
    password: str

class UserResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    is_active: bool
    created_at: datetime


class Token(BaseModel):

    access_token: str
    token_type: str

class TokenData(BaseModel):
    user_id: int | None=None 

