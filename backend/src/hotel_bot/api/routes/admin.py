"""Authenticated administration HTTP contracts with explicit RBAC."""

import math
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    Security,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from hotel_bot.application.admin import AdminAuthService
from hotel_bot.application.evaluation import OfflineEvaluationService
from hotel_bot.application.knowledge import KnowledgeManagementService
from hotel_bot.core.config import Settings
from hotel_bot.dependencies import (
    get_admin_runtime,
    get_database_manager,
    get_settings,
)
from hotel_bot.domain.admin.errors import (
    AdminAuthenticationError,
    AdminAuthorizationError,
    AdminRateLimitError,
    AdminResourceNotFoundError,
    AdminValidationError,
)
from hotel_bot.domain.admin.models import (
    AdminPrincipal,
    ConversationAdminDetail,
    ConversationAdminItem,
    EvaluationAdminItem,
    FeedbackAdminItem,
    KnowledgeAdminDetail,
    KnowledgeAdminItem,
    ServiceRequestAdminItem,
)
from hotel_bot.domain.conversation.enums import ConversationStatus
from hotel_bot.domain.hotel.enums import ServiceRequestStatus, ServiceRequestType, Urgency
from hotel_bot.domain.hotel.errors import InvalidStatusTransition
from hotel_bot.domain.knowledge.enums import KnowledgeStatus, SourceFormat
from hotel_bot.domain.knowledge.errors import KnowledgeError
from hotel_bot.infrastructure.admin_runtime import AdminApplicationRuntime
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.repositories.admin import SQLAlchemyAdminRepository
from hotel_bot.infrastructure.repositories.knowledge import SQLAlchemyKnowledgeRepository
from hotel_bot.persistence.enums import AdminRole, EscalationStatus, EvaluationStatus

router = APIRouter()
bearer = HTTPBearer(auto_error=False)
BACKEND_ROOT = Path(__file__).resolve().parents[4]

ALL_ROLES = frozenset({AdminRole.ADMIN, AdminRole.SUPPORT, AdminRole.EVALUATOR})
ADMIN_ONLY = frozenset({AdminRole.ADMIN})
OPERATIONS_ROLES = frozenset({AdminRole.ADMIN, AdminRole.SUPPORT})
EVALUATION_ROLES = frozenset({AdminRole.ADMIN, AdminRole.EVALUATOR})


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=12, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    admin: AdminPrincipal


class ConversationPage(BaseModel):
    items: tuple[ConversationAdminItem, ...]
    page: int
    page_size: int
    total: int
    pages: int


class KnowledgePage(BaseModel):
    items: tuple[KnowledgeAdminItem, ...]
    page: int
    page_size: int
    total: int
    pages: int


class ServiceRequestPage(BaseModel):
    items: tuple[ServiceRequestAdminItem, ...]
    page: int
    page_size: int
    total: int
    pages: int


class EvaluationPage(BaseModel):
    items: tuple[EvaluationAdminItem, ...]
    page: int
    page_size: int
    total: int
    pages: int


class KnowledgeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=255)
    language: Literal["ar", "en"]
    source_format: SourceFormat = SourceFormat.PLAIN_TEXT
    content: str = Field(min_length=20, max_length=100_000)


class KnowledgeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=3, max_length=255)
    content: str = Field(min_length=20, max_length=100_000)


class KnowledgeMutationResponse(BaseModel):
    document_id: UUID
    revision_id: UUID | None
    version: int | None
    status: KnowledgeStatus


class KnowledgeApprovalResponse(BaseModel):
    document_id: UUID
    current_revision_id: UUID
    status: KnowledgeStatus


class ReindexResponse(BaseModel):
    index_version_id: UUID
    status: Literal["building"] = "building"
    embedding_model: str
    document_count: int
    chunk_count: int


class ServiceStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ServiceRequestStatus


class EvaluatorFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: int | None = Field(default=None, ge=1, le=5)
    label: str | None = Field(default=None, min_length=2, max_length=64, pattern=r"^[a-z0-9_.-]+$")
    comment: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_signal(self) -> "EvaluatorFeedbackRequest":
        if self.rating is None and self.label is None:
            raise ValueError("rating or label is required")
        return self


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: Literal["hotel-support-baseline-v1"] = "hotel-support-baseline-v1"


def _service(
    session: object, runtime: AdminApplicationRuntime, settings: Settings
) -> AdminAuthService:
    from sqlalchemy.ext.asyncio import AsyncSession

    if runtime.token_codec is None:
        raise HTTPException(status_code=503, detail="admin_auth_not_configured")
    if not isinstance(session, AsyncSession):
        raise TypeError("administration authentication requires AsyncSession")
    return AdminAuthService(
        SQLAlchemyAdminRepository(session),
        runtime.token_codec,
        max_login_attempts=settings.admin_login_max_attempts,
        login_window_minutes=settings.admin_login_window_minutes,
    )


async def current_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdminPrincipal:
    token = (
        credentials.credentials
        if credentials and credentials.scheme.casefold() == "bearer"
        else None
    )
    async with database.session() as session:
        try:
            principal = await _service(session, runtime, settings).authenticate(
                token=token,
                correlation_id=str(request.state.correlation_id),
                resource=request.url.path,
            )
        except AdminAuthenticationError as exc:
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=exc.code,
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        await session.commit()
        return principal


async def _authorize(
    principal: AdminPrincipal,
    roles: frozenset[AdminRole],
    *,
    request: Request,
    database: DatabaseManager,
    runtime: AdminApplicationRuntime,
    settings: Settings,
) -> None:
    async with database.session() as session:
        try:
            await _service(session, runtime, settings).authorize(
                principal,
                allowed_roles=roles,
                correlation_id=str(request.state.correlation_id),
                resource=request.url.path,
            )
        except AdminAuthorizationError as exc:
            await session.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.code) from exc
        await session.commit()


def _pages(total: int, page_size: int) -> int:
    return math.ceil(total / page_size) if total else 0


def _not_found(exc: AdminResourceNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.code)


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    async with database.session() as session:
        try:
            result = await _service(session, runtime, settings).login(
                identifier=payload.identifier,
                password=payload.password.get_secret_value(),
                correlation_id=str(request.state.correlation_id),
            )
        except AdminRateLimitError as exc:
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=exc.code,
                headers={"Retry-After": str(settings.admin_login_window_minutes * 60)},
            ) from exc
        except AdminAuthenticationError as exc:
            await session.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.code) from exc
        await session.commit()
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        admin=result.principal,
    )


@router.get("/auth/me", response_model=AdminPrincipal)
async def me(principal: Annotated[AdminPrincipal, Depends(current_admin)]) -> AdminPrincipal:
    return principal


@router.get("/conversations", response_model=ConversationPage)
async def list_conversations(
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
    search: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    conversation_status: Annotated[ConversationStatus | None, Query(alias="status")] = None,
    language: Literal["ar", "en"] | None = None,
    intent: Annotated[str | None, Query(min_length=2, max_length=64)] = None,
    escalation_status: EscalationStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ConversationPage:
    await _authorize(
        principal, ALL_ROLES, request=request, database=database, runtime=runtime, settings=settings
    )
    async with database.session() as session:
        items, total = await SQLAlchemyAdminRepository(session).list_conversations(
            search=search,
            status=conversation_status,
            language=language,
            intent=intent,
            escalation_status=escalation_status,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
    return ConversationPage(
        items=items, page=page, page_size=page_size, total=total, pages=_pages(total, page_size)
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationAdminDetail)
async def get_conversation(
    conversation_id: UUID,
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> ConversationAdminDetail:
    await _authorize(
        principal, ALL_ROLES, request=request, database=database, runtime=runtime, settings=settings
    )
    try:
        async with database.session() as session:
            return await SQLAlchemyAdminRepository(session).get_conversation(conversation_id)
    except AdminResourceNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/knowledge", response_model=KnowledgePage)
async def list_knowledge(
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
    search: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    knowledge_status: Annotated[KnowledgeStatus | None, Query(alias="status")] = None,
    language: Literal["ar", "en"] | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> KnowledgePage:
    await _authorize(
        principal,
        ADMIN_ONLY,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    async with database.session() as session:
        items, total = await SQLAlchemyAdminRepository(session).list_knowledge(
            search=search,
            status=knowledge_status,
            language=language,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
    return KnowledgePage(
        items=items, page=page, page_size=page_size, total=total, pages=_pages(total, page_size)
    )


@router.post("/knowledge", response_model=KnowledgeMutationResponse, status_code=201)
async def create_knowledge(
    payload: KnowledgeCreateRequest,
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> KnowledgeMutationResponse:
    await _authorize(
        principal,
        ADMIN_ONLY,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    try:
        async with database.transaction() as session:
            document, revision = await KnowledgeManagementService(
                SQLAlchemyKnowledgeRepository(session)
            ).create_document(
                admin_id=principal.id,
                title=payload.title,
                language=payload.language,
                source_format=payload.source_format,
                content=payload.content,
            )
    except KnowledgeError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    return KnowledgeMutationResponse(
        document_id=document.id,
        revision_id=revision.id,
        version=revision.version,
        status=document.status,
    )


@router.get("/knowledge/{document_id}", response_model=KnowledgeAdminDetail)
async def get_knowledge(
    document_id: UUID,
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> KnowledgeAdminDetail:
    await _authorize(
        principal,
        ADMIN_ONLY,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    try:
        async with database.session() as session:
            return await SQLAlchemyAdminRepository(session).get_knowledge(document_id)
    except AdminResourceNotFoundError as exc:
        raise _not_found(exc) from exc


@router.patch("/knowledge/{document_id}", response_model=KnowledgeMutationResponse)
async def update_knowledge(
    document_id: UUID,
    payload: KnowledgeUpdateRequest,
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> KnowledgeMutationResponse:
    await _authorize(
        principal,
        ADMIN_ONLY,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    try:
        async with database.transaction() as session:
            repository = SQLAlchemyKnowledgeRepository(session)
            revision = await KnowledgeManagementService(repository).update_document(
                admin_id=principal.id,
                document_id=document_id,
                title=payload.title,
                content=payload.content,
            )
            detail = await SQLAlchemyAdminRepository(session).get_knowledge(document_id)
    except KnowledgeError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    return KnowledgeMutationResponse(
        document_id=document_id,
        revision_id=revision.id,
        version=revision.version,
        status=detail.document.status,
    )


@router.post(
    "/knowledge/{document_id}/revisions/{revision_id}/approve",
    response_model=KnowledgeApprovalResponse,
)
async def approve_knowledge(
    document_id: UUID,
    revision_id: UUID,
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> KnowledgeApprovalResponse:
    await _authorize(
        principal,
        ADMIN_ONLY,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    try:
        async with database.transaction() as session:
            document = await KnowledgeManagementService(
                SQLAlchemyKnowledgeRepository(session)
            ).approve_revision(
                admin_id=principal.id,
                document_id=document_id,
                revision_id=revision_id,
            )
    except KnowledgeError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    if document.current_revision_id is None:
        raise HTTPException(status_code=500, detail="knowledge_approval_invariant_failed")
    return KnowledgeApprovalResponse(
        document_id=document.id,
        current_revision_id=document.current_revision_id,
        status=document.status,
    )


@router.delete("/knowledge/{document_id}", status_code=204)
async def archive_knowledge(
    document_id: UUID,
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> Response:
    await _authorize(
        principal,
        ADMIN_ONLY,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    try:
        async with database.transaction() as session:
            await KnowledgeManagementService(
                SQLAlchemyKnowledgeRepository(session)
            ).archive_document(admin_id=principal.id, document_id=document_id)
    except KnowledgeError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    return Response(status_code=204)


@router.post("/knowledge/reindex", response_model=ReindexResponse, status_code=202)
async def reindex_knowledge(
    request: Request,
    background_tasks: BackgroundTasks,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> ReindexResponse:
    await _authorize(
        principal,
        ADMIN_ONLY,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    try:
        async with database.transaction() as session:
            plan = await runtime.prepare_reindex(session, admin_id=principal.id)
    except KnowledgeError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc
    background_tasks.add_task(runtime.complete_reindex, database, plan)
    return ReindexResponse(
        index_version_id=plan.index.id,
        embedding_model=plan.index.embedding_model,
        document_count=len({item.document_id for item in plan.revisions}),
        chunk_count=len(plan.chunks),
    )


@router.get("/service-requests", response_model=ServiceRequestPage)
async def list_service_requests(
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
    search: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    request_status: Annotated[ServiceRequestStatus | None, Query(alias="status")] = None,
    urgency: Urgency | None = None,
    request_type: ServiceRequestType | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ServiceRequestPage:
    await _authorize(
        principal,
        OPERATIONS_ROLES,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    async with database.session() as session:
        items, total = await SQLAlchemyAdminRepository(session).list_service_requests(
            search=search,
            status=request_status,
            urgency=urgency,
            request_type=request_type,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
    return ServiceRequestPage(
        items=items, page=page, page_size=page_size, total=total, pages=_pages(total, page_size)
    )


@router.patch("/service-requests/{request_id}/status", response_model=ServiceRequestAdminItem)
async def update_service_request_status(
    request_id: UUID,
    payload: ServiceStatusRequest,
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> ServiceRequestAdminItem:
    await _authorize(
        principal,
        OPERATIONS_ROLES,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    try:
        async with database.transaction() as session:
            return await SQLAlchemyAdminRepository(session).transition_service_request(
                request_id=request_id,
                target=payload.status,
                principal=principal,
                correlation_id=str(request.state.correlation_id),
            )
    except AdminResourceNotFoundError as exc:
        raise _not_found(exc) from exc
    except InvalidStatusTransition as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc


@router.post("/messages/{message_id}/feedback", response_model=FeedbackAdminItem, status_code=201)
async def create_evaluator_feedback(
    message_id: UUID,
    payload: EvaluatorFeedbackRequest,
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> FeedbackAdminItem:
    await _authorize(
        principal,
        EVALUATION_ROLES,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    try:
        async with database.transaction() as session:
            return await SQLAlchemyAdminRepository(session).create_evaluator_feedback(
                message_id=message_id,
                rating=payload.rating,
                label=payload.label,
                comment=payload.comment,
                principal=principal,
                correlation_id=str(request.state.correlation_id),
            )
    except AdminResourceNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/evaluations", response_model=EvaluationAdminItem, status_code=201)
async def run_evaluation(
    payload: EvaluationRequest,
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> EvaluationAdminItem:
    await _authorize(
        principal,
        EVALUATION_ROLES,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    try:
        async with database.transaction() as session:
            return await OfflineEvaluationService(
                SQLAlchemyAdminRepository(session),
                backend_root=BACKEND_ROOT,
            ).run(
                dataset_version=payload.dataset_version,
                principal=principal,
                correlation_id=str(request.state.correlation_id),
                app_version=settings.app_version,
                llm_model=settings.gemini_model,
            )
    except AdminValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.code) from exc


@router.get("/evaluations", response_model=EvaluationPage)
async def list_evaluations(
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
    evaluation_status: Annotated[EvaluationStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> EvaluationPage:
    await _authorize(
        principal,
        EVALUATION_ROLES,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    async with database.session() as session:
        items, total = await SQLAlchemyAdminRepository(session).list_evaluations(
            status=evaluation_status,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
    return EvaluationPage(
        items=items, page=page, page_size=page_size, total=total, pages=_pages(total, page_size)
    )


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationAdminItem)
async def get_evaluation(
    evaluation_id: UUID,
    request: Request,
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> EvaluationAdminItem:
    await _authorize(
        principal,
        EVALUATION_ROLES,
        request=request,
        database=database,
        runtime=runtime,
        settings=settings,
    )
    try:
        async with database.session() as session:
            return await SQLAlchemyAdminRepository(session).get_evaluation(evaluation_id)
    except AdminResourceNotFoundError as exc:
        raise _not_found(exc) from exc
