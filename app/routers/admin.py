from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, require_admin
from app.models import (
    AuditLog,
    CollaborationRun,
    ModelCatalog,
    UsageEvent,
    User,
    WorkflowRun,
    Workspace,
    WorkspaceMember,
)
from app.schemas import (
    AdminMemberOut,
    AdminModelOut,
    AdminModelToggleIn,
    AdminPlanChangeIn,
    AdminRunCountsOut,
    AdminRunSummaryOut,
    AdminUsageBucketOut,
    AdminUsageOut,
    AdminWorkspaceOut,
    AuditLogOut,
    UserOut,
)
from app.services.usage_stats import bucket_expression, resolve_range

router = APIRouter(prefix="/admin", tags=["admin"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminContext = Annotated[AuthContext, Depends(require_admin)]


def _range(from_ts: datetime | None, to_ts: datetime | None) -> tuple[datetime, datetime]:
    try:
        return resolve_range(from_ts, to_ts)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


@router.get("/users", response_model=list[UserOut])
async def list_users(
    context: AdminContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: UUID | None = None,
) -> list[User]:
    conditions = []
    if before is not None:
        conditions.append(User.id < before)
    result = await session.execute(
        select(User).where(*conditions).order_by(User.id.desc()).limit(limit)
    )
    return list(result.scalars())


@router.get("/workspaces", response_model=list[AdminWorkspaceOut])
async def list_workspaces(
    context: AdminContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: UUID | None = None,
) -> list[AdminWorkspaceOut]:
    member_count = (
        select(func.count())
        .select_from(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == Workspace.id)
        .scalar_subquery()
    )
    conditions = []
    if before is not None:
        conditions.append(Workspace.id < before)
    rows = (
        await session.execute(
            select(Workspace, member_count.label("member_count"))
            .where(*conditions)
            .order_by(Workspace.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        AdminWorkspaceOut(
            id=workspace.id,
            name=workspace.name,
            plan=workspace.plan,
            is_personal=workspace.is_personal,
            member_count=count,
            created_at=workspace.created_at,
        )
        for workspace, count in rows
    ]


@router.patch("/workspaces/{workspace_id}/plan", response_model=AdminWorkspaceOut)
async def change_workspace_plan(
    workspace_id: UUID,
    payload: AdminPlanChangeIn,
    context: AdminContext,
    session: SessionDep,
) -> AdminWorkspaceOut:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    previous = workspace.plan
    if previous != payload.plan:
        workspace.plan = payload.plan
        session.add(
            AuditLog(
                actor_user_id=context.user.id,
                action="workspace.plan_change",
                target_type="workspace",
                target_id=str(workspace.id),
                detail={"from": previous, "to": payload.plan},
            )
        )
    await session.commit()
    await session.refresh(workspace)
    member_count = (
        await session.execute(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace.id)
        )
    ).scalar_one()
    return AdminWorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        plan=workspace.plan,
        is_personal=workspace.is_personal,
        member_count=member_count,
        created_at=workspace.created_at,
    )


@router.get("/runs/summary", response_model=AdminRunSummaryOut)
async def run_failure_summary(context: AdminContext, session: SessionDep) -> AdminRunSummaryOut:
    async def counts(model) -> AdminRunCountsOut:
        total = (await session.execute(select(func.count()).select_from(model))).scalar_one()
        failed = (
            await session.execute(
                select(func.count()).select_from(model).where(model.status == "failed")
            )
        ).scalar_one()
        rate = round(failed / total, 4) if total else 0.0
        return AdminRunCountsOut(total=total, failed=failed, failure_rate=rate)

    return AdminRunSummaryOut(
        workflows=await counts(WorkflowRun),
        collaborations=await counts(CollaborationRun),
    )


@router.get("/workspaces/{workspace_id}/members", response_model=list[AdminMemberOut])
async def list_workspace_members(
    workspace_id: UUID, context: AdminContext, session: SessionDep
) -> list[AdminMemberOut]:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    rows = (
        await session.execute(
            select(WorkspaceMember, User.email)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.created_at, WorkspaceMember.user_id)
        )
    ).all()
    return [
        AdminMemberOut(
            user_id=member.user_id,
            email=email,
            role=member.role,
            created_at=member.created_at,
        )
        for member, email in rows
    ]


@router.get("/usage", response_model=AdminUsageOut)
async def admin_usage(
    context: AdminContext,
    session: SessionDep,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    group_by: Literal["day", "provider", "model"] = "day",
) -> AdminUsageOut:
    start_at, end_at = _range(from_ts, to_ts)
    bucket = bucket_expression(group_by)
    statement = (
        select(
            bucket.label("bucket"),
            func.count().label("requests"),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(UsageEvent.cost), 0.0).label("cost"),
            func.coalesce(func.sum(case((UsageEvent.unpriced.is_(True), 1), else_=0)), 0).label(
                "unpriced_requests"
            ),
        )
        .where(UsageEvent.created_at >= start_at, UsageEvent.created_at <= end_at)
        .group_by(bucket)
        .order_by(bucket)
    )
    rows = (await session.execute(statement)).all()
    buckets = [
        AdminUsageBucketOut(
            key=str(row.bucket),
            requests=row.requests,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            total_tokens=row.prompt_tokens + row.completion_tokens,
            cost=round(float(row.cost), 6),
            unpriced_requests=row.unpriced_requests,
        )
        for row in rows
    ]
    return AdminUsageOut(
        start=start_at,
        end=end_at,
        group_by=group_by,
        requests=sum(item.requests for item in buckets),
        prompt_tokens=sum(item.prompt_tokens for item in buckets),
        completion_tokens=sum(item.completion_tokens for item in buckets),
        total_tokens=sum(item.total_tokens for item in buckets),
        total_cost=round(sum(item.cost for item in buckets), 6),
        unpriced_requests=sum(item.unpriced_requests for item in buckets),
        buckets=buckets,
    )


@router.get("/models", response_model=list[AdminModelOut])
async def list_admin_models(context: AdminContext, session: SessionDep) -> list[AdminModelOut]:
    rows = (
        await session.execute(
            select(ModelCatalog).order_by(
                ModelCatalog.priority, ModelCatalog.provider_id, ModelCatalog.model_id
            )
        )
    ).scalars()
    return [
        AdminModelOut(
            id=entry.id,
            provider_id=entry.provider_id,
            model_id=entry.model_id,
            display_name=entry.display_name,
            enabled=entry.enabled,
        )
        for entry in rows
    ]


@router.patch("/models/{model_id}", response_model=AdminModelOut)
async def toggle_model(
    model_id: UUID,
    payload: AdminModelToggleIn,
    context: AdminContext,
    session: SessionDep,
) -> AdminModelOut:
    entry = await session.get(ModelCatalog, model_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found")
    entry.enabled = payload.enabled
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="model.toggle",
            target_type="model_catalog",
            target_id=str(entry.id),
            detail={"enabled": payload.enabled},
        )
    )
    await session.commit()
    await session.refresh(entry)
    return AdminModelOut(
        id=entry.id,
        provider_id=entry.provider_id,
        model_id=entry.model_id,
        display_name=entry.display_name,
        enabled=entry.enabled,
    )


@router.get("/audit-logs", response_model=list[AuditLogOut])
async def list_audit_logs(
    context: AdminContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: UUID | None = None,
) -> list[AuditLogOut]:
    conditions = []
    if before is not None:
        conditions.append(AuditLog.id < before)
    rows = (
        await session.execute(
            select(AuditLog, User.email)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .where(*conditions)
            .order_by(AuditLog.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        AuditLogOut(
            id=entry.id,
            actor_user_id=entry.actor_user_id,
            actor_email=email,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            detail=entry.detail,
            created_at=entry.created_at,
        )
        for entry, email in rows
    ]
