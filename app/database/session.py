from sqlalchemy.ext.asyncio import (
    create_async_engine, 
    async_sessionmaker,
    AsyncSession
)
from sqlalchemy.orm import DeclarativeBase
from app.config import settings
from typing import AsyncGenerator

engine = create_async_engine(

    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=12,
    max_overflow=20,
    pool_recycle=3660,
    pool_pre_ping= True,
    connect_args={
        "command_timeout":30, 
    }
)

AsyncSessionLocal = async_sessionmaker(

    engine,
    class_=AsyncSession,
    expire_on_commit=False,

)

Base = DeclarativeBase()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session 
