
import logging
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from app.config import settings
from app.auth.schemas import TokenData
from app.exceptions import InvalidCredentials

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hashpasswordfunction(plain_password: str) -> str:
    return pwd_context.hash(plain_password)

def verify_password(plain_password, hasshed_password):
    
    try:
        return pwd_context.verify(plain_password, hasshed_password)

    except Exception as e:
        logging.warning(" Password verification error")
        return False
    
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:


    to_encode = data.copy()
 
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
 
    to_encode.update({"exp": expire, "type": "access"})
 
    try:
        token = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM
        )
        logging.debug(f"[utils.create_access_token] Token created for sub={data.get('sub')}")
        return token
    except Exception as e:
        logging.error(f"[utils.create_access_token] Failed to encode token: {e}")
        raise
 
 
def create_refresh_token(data: dict) -> str:


    to_encode = data.copy()
 
    expire = datetime.now(timezone.utc) + timedelta(days=7)
    to_encode.update({"exp": expire, "type": "refresh"})
 
    try:
        token = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM
        )
        logging.info(f"[utils.create_refresh_token] Refresh token created for sub={data.get('sub')}")
        return token
    except Exception as e:
        logging.error(f"[utils.create_refresh_token] Failed to encode refresh token: {e}")
        raise
 
 
def decode_access_token(token: str) -> TokenData:

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
 
        # Reject refresh tokens being used as access tokens
        token_type: str = payload.get("type")
        if token_type != "access":
            logging.warning(f"[utils.decode_access_token] Wrong token type: {token_type}")
            raise InvalidCredentials("Invalid token type")
 
        user_id: str | None = payload.get("sub")
        if user_id is None:
            logging.warning("[utils.decode_access_token] Token missing 'sub' claim")
            raise InvalidCredentials("Token missing subject claim")
 
        logging.debug(f"[utils.decode_access_token] Valid token for user_id={user_id}")
        return TokenData(user_id=int(user_id))
 
    except JWTError as e:
        logging.warning(f"[utils.decode_access_token] JWT validation failed: {e}")
        raise InvalidCredentials("Token is invalid or expired")

