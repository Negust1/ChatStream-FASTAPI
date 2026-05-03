
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class settings(BaseSettings):

    DATABSE_URL: str
    REDIS_URL: str
    ALGORITHM: str
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    ANTHROPIC_API_KEY: str
    model_config = SettingsConfigDict(env_file=".env")


@lru_cache()
def get_settings() -> Settings: ...

settings = get_settings()