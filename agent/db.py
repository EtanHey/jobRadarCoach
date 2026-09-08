import asyncio
import json
import os
from weakref import WeakKeyDictionary

import asyncpg

_pools: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncpg.Pool] = WeakKeyDictionary()
_pool_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()


async def _configure_connection(conn: asyncpg.Connection) -> None:
    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(
            type_name,
            schema="pg_catalog",
            encoder=json.dumps,
            decoder=json.loads,
            format="text",
        )


async def pool() -> asyncpg.Pool:
    loop = asyncio.get_running_loop()
    lock = _pool_locks.setdefault(loop, asyncio.Lock())
    async with lock:
        db_pool = _pools.get(loop)
        if db_pool is None or db_pool.is_closing():
            db_pool = await asyncpg.create_pool(
                os.environ["DATABASE_URL"],
                min_size=1,
                max_size=4,
                init=_configure_connection,
                server_settings=(
                    {"default_transaction_read_only": "on"}
                    if os.environ.get("VOICE_QA_MODE", "").strip().casefold()
                    in {"1", "true", "yes", "on"}
                    else None
                ),
            )
            _pools[loop] = db_pool
        return db_pool


async def close_pool() -> None:
    loop = asyncio.get_running_loop()
    db_pool = _pools.pop(loop, None)
    _pool_locks.pop(loop, None)
    if db_pool is not None and not db_pool.is_closing():
        await db_pool.close()
