from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, require_admin
from app.models import AuditLog, DatabaseConnection
from app.schemas import (
    DatabaseConnectionIn,
    DatabaseConnectionOptionOut,
    DatabaseConnectionOut,
    DatabaseConnectionUpdate,
)
from app.services.database_nodes import (
    DatabaseNodeError,
    dsn_hint,
    normalize_dsn,
    test_connection,
)
from app.services.provider_secrets import encrypt_api_key

router = APIRouter(prefix="/database-connections", tags=["database"])
admin_router = APIRouter(prefix="/admin/database-connections", tags=["admin"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
AdminContext = Annotated[AuthContext, Depends(require_admin)]


def _out(connection: DatabaseConnection) -> DatabaseConnectionOut:
    return DatabaseConnectionOut(
        id=connection.id,
        name=connection.name,
        description=connection.description,
        enabled=connection.enabled,
        max_rows=connection.max_rows,
        timeout_seconds=connection.timeout_seconds,
        dsn_hint=connection.dsn_hint,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _error(exc: DatabaseNodeError, code: int = status.HTTP_422_UNPROCESSABLE_CONTENT):
    return HTTPException(code, {"code": exc.code, "message": exc.message})


async def _get(session: AsyncSession, connection_id: UUID) -> DatabaseConnection:
    connection = await session.get(DatabaseConnection, connection_id)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database connection not found")
    return connection


async def _ensure_unique(
    session: AsyncSession, name: str, exclude_id: UUID | None = None
) -> None:
    statement = select(DatabaseConnection.id).where(DatabaseConnection.name == name)
    if exclude_id is not None:
        statement = statement.where(DatabaseConnection.id != exclude_id)
    if (await session.execute(statement)).scalar_one_or_none() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "duplicate", "message": "Database connection name already exists"},
        )


@router.get("", response_model=list[DatabaseConnectionOptionOut])
async def list_available_connections(
    context: JwtContext, session: SessionDep
) -> list[DatabaseConnectionOptionOut]:
    rows = await session.execute(
        select(DatabaseConnection)
        .where(DatabaseConnection.enabled.is_(True))
        .order_by(DatabaseConnection.name)
    )
    return [
        DatabaseConnectionOptionOut(
            id=connection.id,
            name=connection.name,
            description=connection.description,
        )
        for connection in rows.scalars()
    ]


@admin_router.get("", response_model=list[DatabaseConnectionOut])
async def list_admin_connections(
    context: AdminContext, session: SessionDep
) -> list[DatabaseConnectionOut]:
    rows = await session.execute(
        select(DatabaseConnection).order_by(DatabaseConnection.name)
    )
    return [_out(connection) for connection in rows.scalars()]


@admin_router.post(
    "", response_model=DatabaseConnectionOut, status_code=status.HTTP_201_CREATED
)
async def create_admin_connection(
    payload: DatabaseConnectionIn,
    context: AdminContext,
    session: SessionDep,
) -> DatabaseConnectionOut:
    try:
        normalize_dsn(payload.dsn)
    except DatabaseNodeError as exc:
        raise _error(exc) from None
    await _ensure_unique(session, payload.name)
    connection = DatabaseConnection(
        name=payload.name,
        description=payload.description,
        enabled=payload.enabled,
        max_rows=payload.max_rows,
        timeout_seconds=payload.timeout_seconds,
        dsn_encrypted=encrypt_api_key(payload.dsn.strip()),
        dsn_hint=dsn_hint(payload.dsn),
    )
    session.add(connection)
    await session.flush()
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="database_connection.create",
            target_type="database_connection",
            target_id=str(connection.id),
            detail={"name": connection.name},
        )
    )
    await session.commit()
    await session.refresh(connection)
    return _out(connection)


@admin_router.patch("/{connection_id}", response_model=DatabaseConnectionOut)
async def update_admin_connection(
    connection_id: UUID,
    payload: DatabaseConnectionUpdate,
    context: AdminContext,
    session: SessionDep,
) -> DatabaseConnectionOut:
    connection = await _get(session, connection_id)
    values = payload.model_dump(exclude_unset=True)
    if "name" in values and values["name"] is not None:
        await _ensure_unique(session, values["name"], exclude_id=connection.id)
    dsn = values.pop("dsn", None)
    if dsn is not None:
        try:
            normalize_dsn(dsn)
        except DatabaseNodeError as exc:
            raise _error(exc) from None
        connection.dsn_encrypted = encrypt_api_key(dsn.strip())
        connection.dsn_hint = dsn_hint(dsn)
    for key, value in values.items():
        if value is not None:
            setattr(connection, key, value)
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="database_connection.update",
            target_type="database_connection",
            target_id=str(connection.id),
            detail={"name": connection.name, "fields": sorted(values)},
        )
    )
    await session.commit()
    await session.refresh(connection)
    return _out(connection)


@admin_router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_connection(
    connection_id: UUID, context: AdminContext, session: SessionDep
) -> Response:
    connection = await _get(session, connection_id)
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="database_connection.delete",
            target_type="database_connection",
            target_id=str(connection.id),
            detail={"name": connection.name},
        )
    )
    await session.delete(connection)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post("/{connection_id}/test")
async def test_admin_connection(
    connection_id: UUID, context: AdminContext, session: SessionDep
) -> dict[str, object]:
    connection = await _get(session, connection_id)
    try:
        value = await test_connection(connection)
    except DatabaseNodeError as exc:
        raise _error(exc, status.HTTP_502_BAD_GATEWAY) from None
    return {"ok": True, "value": value}