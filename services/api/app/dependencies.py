from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import Principal, current_principal
from .database import tenant_session


async def get_tenant_db(
    principal: Principal = Depends(current_principal),
) -> AsyncIterator[AsyncSession]:
    async for session in tenant_session(principal.tenant_id):
        yield session
