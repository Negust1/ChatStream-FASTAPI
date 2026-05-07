import logging
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
import redis.asyncio as aioredis

from app.auth.models import UserModel
from app.auth.schemas import UserCreate

logger = logging.getLogger(__name__)

# Redis key helpers — namespaced and consistent
def _user_id_key(user_id: int) -> str:
    return f"user:id:{user_id}"

def _user_email_key(email: str) -> str:
    return f"user:email:{email}"

USER_CACHE_TTL = 300  #  5 minutes


class UserRepo:

    def _serialize_user(self, user: UserModel) -> str:
        return json.dumps({
            "id": user.id,
            "email": user.email,
            "hashed_password": user.hashed_password,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
        })

    def _deserialize_user(self, data: str) -> dict:
        return json.loads(data)

    async def _invalidate_user_cache(
        self,
        redis: aioredis.Redis,
        user_id: int,
        email: str
    ) -> None:
        """Remove all cached entries for a user on write operations."""
        try:
            await redis.delete(_user_id_key(user_id), _user_email_key(email))
        except Exception as e:
            # Cache invalidation failure must never break a write operation
            logger.warning(f"[UserRepo] Cache invalidation failed for user_id={user_id}: {e}")


    async def get_by_id( self, user_id: int, db: AsyncSession, redis: aioredis.Redis) -> UserModel | None:
        """
        Fetch a single user by primary key.
        Checks Redis first. Falls back to Postgres on cache miss.
        """
        cache_key = _user_id_key(user_id)
        try:
            cached = await redis.get(cache_key)
            if cached:
                logger.debug(f"[UserRepo.get_by_id] Cache HIT for user_id={user_id}")
                data = self._deserialize_user(cached)
                # Reconstruct a lightweight UserModel from cache
                user = UserModel(**data)
                return user
        except Exception as e:
            logger.warning(f"[UserRepo.get_by_id] Redis read failed, falling back to DB: {e}")

        # Cache miss — go to Postgres
        try:
            result = await db.execute(
                select(UserModel).where(UserModel.id == user_id)
            )
            user = result.scalar_one_or_none()
            if user:
                try:
                    await redis.setex(cache_key, USER_CACHE_TTL, self._serialize_user(user))
                except Exception as e:
                    logger.warning(f"[UserRepo.get_by_id] Redis write failed: {e}")
            return user
        except Exception as e:
            logger.error(f"[UserRepo.get_by_id] DB failed for user_id={user_id}: {e}")
            raise

    async def get_by_email(
        self,
        email: str,
        db: AsyncSession,
        redis: aioredis.Redis
    ) -> UserModel | None:
        """
        Fetch a single user by email address.
        Checks Redis first. Falls back to Postgres on cache miss.
        Used for login and duplicate registration checks.
        """
        normalized = email.lower().strip()
        cache_key = _user_email_key(normalized)
        try:
            cached = await redis.get(cache_key)
            if cached:
                logger.debug(f"[UserRepo.get_by_email] Cache HIT for email={normalized}")
                data = self._deserialize_user(cached)
                return UserModel(**data)
        except Exception as e:
            logger.warning(f"[UserRepo.get_by_email] Redis read failed, falling back to DB: {e}")

        try:
            result = await db.execute(
                select(UserModel).where(UserModel.email == normalized)
            )
            user = result.scalar_one_or_none()
            if user:
                try:
                    await redis.setex(cache_key, USER_CACHE_TTL, self._serialize_user(user))
                except Exception as e:
                    logger.warning(f"[UserRepo.get_by_email] Redis write failed: {e}")
            return user
        except Exception as e:
            logger.error(f"[UserRepo.get_by_email] DB failed for email={normalized}: {e}")
            raise



    async def create(
        self,
        data: UserCreate,
        hashed_password: str,
        db: AsyncSession,
        redis: aioredis.Redis
    ) -> UserModel:
        """
        Insert a new user row.
        Password must already be hashed before reaching this method.
        Raises IntegrityError if email already exists — handled by service layer.
        Invalidates any stale cache on success.
        """
        try:
            user = UserModel(
                email=data.email.lower().strip(),
                hashed_password=hashed_password,
                is_active=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            await self._invalidate_user_cache(redis, user.id, user.email)
            logger.info(f"[UserRepo.create] New user created: id={user.id}")
            return user
        except IntegrityError:
            await db.rollback()
            logger.warning(f"[UserRepo.create] Duplicate email attempted: {data.email}")
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"[UserRepo.create] Unexpected error: {e}")
            raise

    async def update_active_status(
        self,
        user_id: int,
        status: bool,
        db: AsyncSession,
        redis: aioredis.Redis
    ) -> None:
        """
        Activate or deactivate a user account.
        Invalidates cache after update so stale data is never served.
        """
        try:
            result = await db.execute(
                select(UserModel).where(UserModel.id == user_id)
            )
            user = result.scalar_one_or_none()

            await db.execute(
                update(UserModel).where(UserModel.id == user_id).values(is_active=status))
            await db.commit()

            if user:
                await self._invalidate_user_cache(redis, user_id, user.email)

            logger.info(f"[UserRepo.update_active_status] user_id={user_id} set to is_active={status}")
        except Exception as e:
            await db.rollback()
            logger.error(f"[UserRepo.update_active_status] Failed for user_id={user_id}: {e}")
            raise



    async def get_all_active(
        self,
        db: AsyncSession,
        redis: aioredis.Redis,
        skip: int = 0,
        limit: int = 20
    ) -> list[UserModel]:

        cache_key = f"users:active:skip={skip}:limit={limit}"
        try:
            cached = await redis.get(cache_key)
            if cached:
                logger.debug(f"[UserRepo.get_all_active] Cache HIT skip={skip} limit={limit}")
                raw_list = json.loads(cached)
                return [UserModel(**u) for u in raw_list]
        except Exception as e:
            logger.warning(f"[UserRepo.get_all_active] Redis read failed: {e}")

        try:
            result = await db.execute(
                select(UserModel).where(UserModel.is_active == True).offset(skip).limit(limit))
            

            users = list(result.scalars().all())


            try:
                serialized = json.dumps([json.loads(self._serialize_user(u)) for u in users])
                await redis.setex(cache_key, USER_CACHE_TTL, serialized)
            except Exception as e:
                logger.warning(f"[UserRepo.get_all_active] Redis write failed: {e}")
            return users
        except Exception as e:
            logger.error(f"[UserRepo.get_all_active] DB failed: {e}")
            raise
    
        