

import logging
import json
import redis.asyncio as aioredis
from sqlalchemy.orm import selectinload
from sqlalchemy import desc, delete, select
from sqlalchemy.ext.asyncio import AsyncSession


from app.chat.models import ChatSession, Message
 
logger = logging.getLogger(__name__)
 
# Redis key helpers — namespaced and consistent
def _session_key(session_id: int) -> str:
    return f"chat:session:{session_id}"
 
def _user_sessions_key(user_id: int, skip: int, limit: int) -> str:
    return f"chat:user:{user_id}:sessions:skip={skip}:limit={limit}"
 
def _messages_key(session_id: int, skip: int, limit: int) -> str:
    return f"chat:session:{session_id}:messages:skip={skip}:limit={limit}"
 
SESSION_CACHE_TTL = 120   # 2 minutes
MESSAGES_CACHE_TTL = 60   # 1 minute — messages change more frequently
 
 
class ChatRepo:
    """
    Data access layer for ChatSession and Message models.
    All reads use Redis caching. All writes invalidate relevant cache keys.
    No business logic. No LLM calls. No HTTP concerns.
    Returns None when sessions not found — never raises domain exceptions.
    """
 
    # -------------------------------------------------------------------------
    # Internal cache helpers
    # -------------------------------------------------------------------------
 
    def _serialize_session(self, session: ChatSession) -> dict:
        return {
            "id": session.id,
            "user_id": session.user_id,
            "title": session.title,
            "created_at": session.created_at.isoformat(),
        }
 
    def _serialize_message(self, message: Message) -> dict:
        return {
            "id": message.id,
            "session_id": message.session_id,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at.isoformat(),
        }
 
    async def _invalidate_session_cache(
        self,
        redis: aioredis.Redis,
        session_id: int,
        user_id: int
    ) -> None:
        """
        Remove single session cache and all paginated session list caches for user.
        Uses Redis key pattern scan — safe because keys are namespaced.
        """
        try:
            await redis.delete(_session_key(session_id))
            # Invalidate all paginated session list pages for this user
            pattern = f"chat:user:{user_id}:sessions:*"
            keys = await redis.keys(pattern)
            if keys:
                await redis.delete(*keys)
        except Exception as e:
            logger.warning(f"[ChatRepo] Session cache invalidation failed session_id={session_id}: {e}")
 
    async def _invalidate_messages_cache(
        self,
        redis: aioredis.Redis,
        session_id: int
    ) -> None:
        """Remove all paginated message cache pages for a session."""
        try:
            pattern = f"chat:session:{session_id}:messages:*"
            keys = await redis.keys(pattern)
            if keys:
                await redis.delete(*keys)
        except Exception as e:
            logger.warning(f"[ChatRepo] Messages cache invalidation failed session_id={session_id}: {e}")
 
    # -------------------------------------------------------------------------
    # Session operations
    # -------------------------------------------------------------------------
 
    async def create_session(
        self,
        user_id: int,
        title: str,
        db: AsyncSession,
        redis: aioredis.Redis
    ) -> ChatSession:
        """
        Create a new chat session for a user.
        Invalidates the user's session list cache so next fetch is fresh.
        """
        try:
            session = ChatSession(
                user_id=user_id,
                title=title or "New Chat",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)
            await self._invalidate_session_cache(redis, session.id, user_id)
            logger.info(f"[ChatRepo.create_session] Created session_id={session.id} for user_id={user_id}")
            return session
        except Exception as e:
            await db.rollback()
            logger.error(f"[ChatRepo.create_session] Failed for user_id={user_id}: {e}")
            raise
 
    async def get_session(
        self,
        session_id: int,
        db: AsyncSession,
        redis: aioredis.Redis
    ) -> ChatSession | None:
        """
        Fetch a single session by ID with Redis cache.
        Eagerly loads messages to avoid lazy load issues in async context.
        """
        cache_key = _session_key(session_id)
        try:
            cached = await redis.get(cache_key)
            if cached:
                logger.debug(f"[ChatRepo.get_session] Cache HIT session_id={session_id}")
                data = json.loads(cached)
                return ChatSession(**data)
        except Exception as e:
            logger.warning(f"[ChatRepo.get_session] Redis read failed, falling back to DB: {e}")
 
        try:
            result = await db.execute(
                select(ChatSession)
                .options(selectinload(ChatSession.messages))
                .where(ChatSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session:
                try:
                    await redis.setex(
                        cache_key,
                        SESSION_CACHE_TTL,
                        json.dumps(self._serialize_session(session))
                    )
                except Exception as e:
                    logger.warning(f"[ChatRepo.get_session] Redis write failed: {e}")
            return session
        except Exception as e:
            logger.error(f"[ChatRepo.get_session] DB failed for session_id={session_id}: {e}")
            raise
 
    async def get_user_sessions(
        self,
        user_id: int,
        db: AsyncSession,
        redis: aioredis.Redis,
        skip: int = 0,
        limit: int = 20
    ) -> list[ChatSession]:
        """
        Return paginated sessions belonging to a user.
        Ordered by most recently created first.
        Each page is cached independently by skip+limit values.
        """
        cache_key = _user_sessions_key(user_id, skip, limit)
        try:
            cached = await redis.get(cache_key)
            if cached:
                logger.debug(f"[ChatRepo.get_user_sessions] Cache HIT user_id={user_id} skip={skip} limit={limit}")
                raw_list = json.loads(cached)
                return [ChatSession(**s) for s in raw_list]
        except Exception as e:
            logger.warning(f"[ChatRepo.get_user_sessions] Redis read failed: {e}")
 
        try:
            result = await db.execute(
                select(ChatSession)
                .where(ChatSession.user_id == user_id)
                .order_by(desc(ChatSession.created_at))
                .offset(skip)
                .limit(limit)
            )
            sessions = list(result.scalars().all())
            try:
                serialized = json.dumps([self._serialize_session(s) for s in sessions])
                await redis.setex(cache_key, SESSION_CACHE_TTL, serialized)
            except Exception as e:
                logger.warning(f"[ChatRepo.get_user_sessions] Redis write failed: {e}")
            return sessions
        except Exception as e:
            logger.error(f"[ChatRepo.get_user_sessions] DB failed for user_id={user_id}: {e}")
            raise
 
    async def delete_session(
        self,
        session_id: int,
        user_id: int,
        db: AsyncSession,
        redis: aioredis.Redis
    ) -> None:
        """
        Hard delete a session and all its messages.
        Cascade delete on the model handles messages automatically.
        Invalidates all related cache entries after deletion.
        """
        try:
            await db.execute(
                delete(ChatSession).where(ChatSession.id == session_id)
            )
            await db.commit()
            await self._invalidate_session_cache(redis, session_id, user_id)
            await self._invalidate_messages_cache(redis, session_id)
            logger.info(f"[ChatRepo.delete_session] Deleted session_id={session_id}")
        except Exception as e:
            await db.rollback()
            logger.error(f"[ChatRepo.delete_session] Failed for session_id={session_id}: {e}")
            raise
 
    # Extra session method
    async def update_session_title(
        self,
        session_id: int,
        user_id: int,
        new_title: str,
        db: AsyncSession,
        redis: aioredis.Redis
    ) -> ChatSession | None:
        """
        Update the title of an existing session.
        Useful when the frontend auto-generates a title from the first message.
        Invalidates cache for this session after update.
        """
        try:
            result = await db.execute(
                select(ChatSession).where(ChatSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if not session:
                return None
            session.title = new_title
            await db.commit()
            await db.refresh(session)
            await self._invalidate_session_cache(redis, session_id, user_id)
            logger.info(f"[ChatRepo.update_session_title] session_id={session_id} renamed to '{new_title}'")
            return session
        except Exception as e:
            await db.rollback()
            logger.error(f"[ChatRepo.update_session_title] Failed for session_id={session_id}: {e}")
            raise
 
    # -------------------------------------------------------------------------
    # Message operations
    # -------------------------------------------------------------------------
 
    async def save_message(
        self,
        session_id: int,
        role: str,
        content: str,
        db: AsyncSession,
        redis: aioredis.Redis
    ) -> Message:
        """
        Persist a single message to a session.
        role must be either 'user' or 'assistant'.
        Invalidates messages cache so next read is fresh from Postgres.
        """
        if role not in ("user", "assistant"):
            raise ValueError(f"[ChatRepo.save_message] Invalid role: '{role}'. Must be 'user' or 'assistant'.")
 
        try:
            message = Message(
                session_id=session_id,
                role=role,
                content=content,
            )
            db.add(message)
            await db.commit()
            await db.refresh(message)
            await self._invalidate_messages_cache(redis, session_id)
            logger.debug(f"[ChatRepo.save_message] Saved message_id={message.id} role={role} session_id={session_id}")
            return message
        except Exception as e:
            await db.rollback()
            logger.error(f"[ChatRepo.save_message] Failed for session_id={session_id}: {e}")
            raise
 
    async def get_session_messages(
        self,
        session_id: int,
        db: AsyncSession,
        redis: aioredis.Redis,
        skip: int = 0,
        limit: int = 20
    ) -> list[Message]:
        """
        Fetch paginated messages from a session ordered chronologically.
        Each page cached independently by skip+limit.
        Used when Redis context cache is cold — rebuilds context window from Postgres.
        Messages are returned in chronological order for correct prompt building.
        """
        cache_key = _messages_key(session_id, skip, limit)
        try:
            cached = await redis.get(cache_key)
            if cached:
                logger.debug(f"[ChatRepo.get_session_messages] Cache HIT session_id={session_id} skip={skip} limit={limit}")
                raw_list = json.loads(cached)
                return [Message(**m) for m in raw_list]
        except Exception as e:
            logger.warning(f"[ChatRepo.get_session_messages] Redis read failed: {e}")
 
        try:
            result = await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(desc(Message.created_at))
                .offset(skip)
                .limit(limit)
            )
            messages = list(result.scalars().all())
            # Reverse to restore chronological order for prompt building
            messages.reverse()
            try:
                serialized = json.dumps([self._serialize_message(m) for m in messages])
                await redis.setex(cache_key, MESSAGES_CACHE_TTL, serialized)
            except Exception as e:
                logger.warning(f"[ChatRepo.get_session_messages] Redis write failed: {e}")
            return messages
        except Exception as e:
            logger.error(f"[ChatRepo.get_session_messages] DB failed for session_id={session_id}: {e}")
            raise
 
    # Extra message method
    async def get_message_count(
        self,
        session_id: int,
        db: AsyncSession,
        redis: aioredis.Redis
    ) -> int:
        """
        Return the total number of messages in a session.
        Used for pagination metadata and enforcing message limits per session.
        Cached with the same TTL as messages since count changes on every save.
        """
        cache_key = f"chat:session:{session_id}:message_count"
        try:
            cached = await redis.get(cache_key)
            if cached:
                logger.debug(f"[ChatRepo.get_message_count] Cache HIT session_id={session_id}")
                return int(cached)
        except Exception as e:
            logger.warning(f"[ChatRepo.get_message_count] Redis read failed: {e}")
 
        try:
            result = await db.execute(
                select(Message).where(Message.session_id == session_id)
            )
            count = len(result.scalars().all())
            try:
                await redis.setex(cache_key, MESSAGES_CACHE_TTL, str(count))
            except Exception as e:
                logger.warning(f"[ChatRepo.get_message_count] Redis write failed: {e}")
            return count
        except Exception as e:
            logger.error(f"[ChatRepo.get_message_count] DB failed for session_id={session_id}: {e}")
            raise