from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import get_current_user, get_registry
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import ProviderOut

router = APIRouter(
    prefix="/providers",
    tags=["providers"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[ProviderOut])
async def list_providers(
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
) -> list[ProviderOut]:
    result: list[ProviderOut] = []
    for provider in registry.all():
        try:
            models = await provider.list_models()
        except ProviderError:
            result.append(ProviderOut(id=provider.id, available=False, models=[]))
        else:
            result.append(
                ProviderOut(
                    id=provider.id,
                    available=True,
                    models=[model.id for model in models],
                )
            )
    return result
