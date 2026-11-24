import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.schemas import GitHubIssueOut, GitHubRepoOut
from app.services.integrations import (
    IntegrationError,
    elapsed_ms,
    list_github_issues,
    list_github_repos,
    log_external_call,
    resolve_config,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _error(exc: IntegrationError) -> HTTPException:
    if exc.code == "not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code in {
        "integration_timeout",
        "integration_unreachable",
        "integration_upstream_error",
        "integration_rate_limited",
        "integration_auth_failed",
        "integration_bad_response",
        "integration_response_too_large",
    }:
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY, {"code": exc.code, "message": exc.message}
        )
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


@router.get("/github/repos", response_model=list[GitHubRepoOut])
async def github_repos(
    context: JwtContext, session: SessionDep, integration_id: str | None = None
) -> list[GitHubRepoOut]:
    try:
        config = await resolve_config(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            kind="github",
            config_id=integration_id,
        )
    except IntegrationError as exc:
        raise _error(exc) from None
    started = time.perf_counter()
    try:
        repos = await list_github_repos(config)
    except IntegrationError as exc:
        log_external_call(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            integration=config,
            operation="github_repos",
            status="failed",
            error_code=exc.code,
            duration_ms=elapsed_ms(started),
        )
        await session.commit()
        raise _error(exc) from None
    log_external_call(
        session,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        integration=config,
        operation="github_repos",
        duration_ms=elapsed_ms(started),
    )
    await session.commit()
    return [GitHubRepoOut(**item) for item in repos]


@router.get("/github/repos/{owner}/{repo}/issues", response_model=list[GitHubIssueOut])
async def github_issues(
    owner: str,
    repo: str,
    context: JwtContext,
    session: SessionDep,
    integration_id: str | None = None,
    state: str = "open",
) -> list[GitHubIssueOut]:
    try:
        config = await resolve_config(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            kind="github",
            config_id=integration_id,
        )
    except IntegrationError as exc:
        raise _error(exc) from None
    started = time.perf_counter()
    try:
        issues = await list_github_issues(config, owner=owner, repo=repo, state=state)
    except IntegrationError as exc:
        log_external_call(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            integration=config,
            operation="github_issues",
            status="failed",
            error_code=exc.code,
            duration_ms=elapsed_ms(started),
        )
        await session.commit()
        raise _error(exc) from None
    log_external_call(
        session,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        integration=config,
        operation="github_issues",
        duration_ms=elapsed_ms(started),
    )
    await session.commit()
    return [GitHubIssueOut(**item) for item in issues]