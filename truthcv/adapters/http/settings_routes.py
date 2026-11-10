"""Settings routes: Jev settings, the v1 provider settings, the model list and model routing."""

from __future__ import annotations

from fastapi import APIRouter

from truthcv.integrations.providers import get_provider
import truthcv.services.settings as settings_service
import truthcv.integrations.modelrouting as modelrouting
import truthcv.infra.secretstore as secretstore

from .route_support import _models_result
from .schemas import (
    JevSettingsStatus,
    JevSettingsUpdate,
    ModelList,
    RouteModel,
    RoutingModel,
    RoutingUpdate,
    SettingsStatus,
    SettingsUpdate,
    TestResult,
)

router = APIRouter()


@router.get("/settings/jev", response_model=JevSettingsStatus)
def get_jev_settings() -> JevSettingsStatus:
    """Whether Jev cross-checking is configured. The key itself is never returned."""
    return JevSettingsStatus(**settings_service.jev_status())


@router.put("/settings/jev", response_model=JevSettingsStatus)
def put_jev_settings(body: JevSettingsUpdate) -> JevSettingsStatus:
    """Save (or, with an empty string, clear) the Jev API key and/or the
    useForScreening / useForEmailTracking toggles. Saving a non-empty key
    requires encryption."""
    status = settings_service.update_jev(
        body.api_key, body.use_for_screening, body.use_for_email_tracking
    )
    return JevSettingsStatus(**status)


@router.post("/settings/jev/test", response_model=TestResult)
def test_jev_settings() -> TestResult:
    """Verify the saved Jev key with one live request."""
    from truthcv.domain.screening import jev

    ok, detail = jev.check_key(secretstore.get_connection("jev").get("apiKey", ""))
    return TestResult(ok=ok, detail=detail)


@router.get("/settings", response_model=SettingsStatus)
def get_settings() -> SettingsStatus:
    return SettingsStatus(**settings_service.settings_status())


@router.post("/settings", response_model=SettingsStatus)
def post_settings(body: SettingsUpdate) -> SettingsStatus:
    """Old single-provider POST shape, shimmed onto the v2 store: the key/host
    lands in that provider's connection, and {connection, model} becomes the
    routing default."""
    status = settings_service.save_v1_settings(
        body.active_provider, body.api_key, body.ollama_host, body.model
    )
    return SettingsStatus(**status)


@router.post("/settings/test", response_model=TestResult)
def test_settings(body: SettingsUpdate) -> TestResult:
    ok, detail = settings_service.test_v1_settings(
        body.active_provider,
        body.api_key,
        body.ollama_host,
        body.model,
        provider_factory=lambda: get_provider(refresh=True),
    )
    return TestResult(ok=ok, detail=detail)


@router.post("/models", response_model=ModelList)
def list_models(body: SettingsUpdate) -> ModelList:
    """Live model list for the selected provider, pulled from its API/SDK."""
    models, card = settings_service.list_v1_models(
        body.active_provider, body.api_key, body.ollama_host
    )
    return _models_result(models, card)


@router.get("/routing", response_model=RoutingModel)
def get_routing() -> RoutingModel:
    """Get the current model routing configuration."""
    return _routing_model(modelrouting.load())


@router.put("/routing", response_model=RoutingModel)
def put_routing(body: RoutingUpdate) -> RoutingModel:
    """Merge only the fields the client sent onto the stored routing.

    A field explicitly sent as null is not the same as an absent field: it
    clears that route (`default`/`agent` sent as null, or a `tasks` entry
    sent as null, removes it) instead of leaving the stored value untouched.
    """
    # Prepare update from body — exclude_unset only, so an explicit null
    # survives into update_dict and is distinguishable from an absent field.
    update_dict = body.model_dump(exclude_unset=True, by_alias=False)
    return _routing_model(settings_service.update_routing(update_dict))


def _routing_model(routing: modelrouting.Routing) -> RoutingModel:
    """Convert a stored Routing to its API wire model."""
    return RoutingModel(
        tasks={k: _route_model(v) for k, v in routing.tasks.items()},
        agent=_route_model(routing.agent) if routing.agent else None,
        default=_route_model(routing.default) if routing.default else None,
        agent_stages={k: _route_model(v) for k, v in routing.agent_stages.items()},
    )


def _route_model(route: modelrouting.Route) -> RouteModel:
    """Convert a stored Route to its API wire model."""
    return RouteModel(
        connection=route.connection,
        model=route.model,
        effort=route.effort,
    )
