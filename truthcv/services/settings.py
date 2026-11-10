"""Settings workflows: the v1 single-provider shim, Jev settings, the live
model list and the routing update.

Moved out of the FastAPI handlers so the logic is framework-free. Errors are
raised as truthcv.services.errors types with the exact status and detail text the
routes returned before the move.
"""

from __future__ import annotations

from collections.abc import Callable

import truthcv.integrations.modelrouting as modelrouting
import truthcv.integrations.providers as _providers
import truthcv.infra.secretstore as secretstore
from truthcv.integrations.connections import catalog
from truthcv.integrations.providers import ProviderError
from truthcv.integrations.providers.base import supports_effort_levels
from truthcv.services.errors import BadGateway, BadRequest, ServiceError

_V1_PROVIDER_TO_CARD = {"anthropic": "claude", "openai": "codex", "ollama": "ollama"}
_CARD_TO_V1_PROVIDER = {v: k for k, v in _V1_PROVIDER_TO_CARD.items()}

_NO_ENCRYPTION = "Set ENCRYPTION_KEY in .env first."


def settings_status() -> dict:
    """The v1 SettingsStatus fields, derived from the v2 store.

    Exists so the GET/POST /settings shim reads one view of the routing
    default and connection secrets.
    """
    routing = modelrouting.load()
    if routing.default is not None:
        active_provider = _CARD_TO_V1_PROVIDER.get(routing.default.connection, routing.default.connection)
        model = routing.default.model
    else:
        card, model = secretstore.legacy_default()
        active_provider = _CARD_TO_V1_PROVIDER.get(card, card or "")
    return {
        "encryption_available": secretstore.encryption_available(),
        "active_provider": active_provider,
        "model": model,
        "anthropic_key_set": bool(secretstore.get_connection("claude").get("apiKey")),
        # OpenAI key is set if the codex card has either an api key or a valid
        # oauth subscription — either mode makes the card usable.
        "openai_key_set": bool(
            secretstore.get_connection("codex").get("apiKey")
            or secretstore.get_connection("codex").get("oauth", {}).get("accessToken")
        ),
        "ollama_host": secretstore.get_connection("ollama").get("baseUrl", ""),
    }


def jev_status() -> dict:
    """Whether Jev cross-checking is configured. The key itself is never returned.

    Exists so GET and PUT /settings/jev shape the same status.
    """
    conn = secretstore.get_connection("jev")
    return {
        "key_set": bool(conn.get("apiKey")),
        "use_for_screening": conn.get("useForScreening") is True,
        "use_for_email_tracking": conn.get("useForEmailTracking") is True,
        "encryption_available": secretstore.encryption_available(),
    }


def update_jev(
    api_key: str | None,
    use_for_screening: bool | None,
    use_for_email_tracking: bool | None,
) -> dict:
    """Save (or, with an empty string, clear) the Jev API key and/or the
    useForScreening / useForEmailTracking toggles. Saving a non-empty key
    requires encryption. Returns the fresh jev_status()."""
    updates: dict = {}
    if api_key is not None:
        updates["apiKey"] = api_key.strip() or None
    if use_for_screening is not None:
        updates["useForScreening"] = use_for_screening
    if use_for_email_tracking is not None:
        updates["useForEmailTracking"] = use_for_email_tracking
    # Any persisted field — including the toggle — is written through the
    # same encrypted store as the key, so a write of either kind needs a
    # valid ENCRYPTION_KEY, not just a non-empty api_key.
    if updates and not secretstore.encryption_available():
        raise BadRequest(_NO_ENCRYPTION)
    if updates:
        secretstore.set_connection("jev", updates)
    return jev_status()


def save_v1_settings(
    active_provider: str,
    api_key: str | None,
    ollama_host: str | None,
    model: str | None,
) -> dict:
    """Old single-provider POST shape, shimmed onto the v2 store: the key/host
    lands in that provider's connection, and {connection, model} becomes the
    routing default. Returns the fresh settings_status()."""
    if not secretstore.encryption_available():
        raise BadRequest(_NO_ENCRYPTION)
    card = _V1_PROVIDER_TO_CARD.get(active_provider, active_provider)
    if card not in catalog.CARDS:
        raise BadRequest(f"Unknown provider '{active_provider}'.")

    updates: dict = {}
    if api_key:  # empty/None leaves the stored key unchanged
        updates["apiKey"] = api_key
    if ollama_host:
        updates["baseUrl"] = ollama_host
    if updates:
        secretstore.set_connection(card, updates)

    routing = modelrouting.load()
    if model is None:
        model = routing.default.model if routing.default else ""
    routing.default = modelrouting.Route(card, model)
    modelrouting.save(routing)

    _providers.reset_provider()
    return settings_status()


def test_v1_settings(
    active_provider: str,
    api_key: str | None,
    ollama_host: str | None,
    model: str | None,
    provider_factory: Callable[[], object],
) -> tuple[bool, str]:
    """Save the v1 settings, then ping the resulting provider.

    Returns (ok, detail) rather than raising, because the Test connection
    route reports every failure, including a rejected save, as a result.
    ``provider_factory`` builds the refreshed provider (the handler owns
    get_provider).
    """
    try:
        save_v1_settings(active_provider, api_key, ollama_host, model)
        provider = provider_factory()
        provider.complete("ping", [{"role": "user", "content": "ping"}])
        return True, "Connection succeeded."
    except ServiceError as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


# Not a pytest test: truthcv/services/ is outside testpaths (tests/), but a test module
# that does `from truthcv.services.settings import test_v1_settings` would otherwise
# collect it.
test_v1_settings.__test__ = False


def _provider_from_update(
    active_provider: str | None,
    api_key: str | None,
    ollama_host: str | None,
):
    """Build a provider from the submitted settings WITHOUT persisting anything.

    Uses a key/host typed in the form if present, otherwise the saved connection
    — so the model list can load with an unsaved key (like Test connection) and
    without writing secrets just to populate a dropdown.
    """
    name = (active_provider or "").strip().lower()
    card = _V1_PROVIDER_TO_CARD.get(name)
    if card is None:
        raise BadRequest(f"Unknown provider '{name}'.")
    conn = secretstore.get_connection(card)
    if card == "claude":
        from truthcv.integrations.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=api_key or conn.get("apiKey") or None)
    if card == "codex":
        from truthcv.integrations.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=api_key or conn.get("apiKey") or None)
    if card == "ollama":
        from truthcv.integrations.providers.ollama_provider import OllamaProvider

        return OllamaProvider(host=ollama_host or conn.get("baseUrl") or None)
    raise BadRequest(f"Unknown provider '{name}'.")


def list_v1_models(
    active_provider: str | None,
    api_key: str | None,
    ollama_host: str | None,
) -> tuple[list[dict], str]:
    """Live model list for the selected provider, pulled from its API/SDK.

    The provider SDK module is imported lazily inside the try, so only the
    selected provider is imported and an import failure maps to BadGateway.
    Returns (models, card) for the handler to shape.
    """
    name = (active_provider or "").strip().lower()
    card = _V1_PROVIDER_TO_CARD.get(name, "")
    try:
        provider = _provider_from_update(active_provider, api_key, ollama_host)
        models = provider.list_models()
    except ServiceError:
        raise
    except ProviderError as e:
        raise BadRequest(str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise BadGateway(f"{type(e).__name__}: {e}") from e
    return models, card


def _validate_routes(update: dict) -> None:
    """Validate all connections and effort levels in the update before applying."""
    for route_dict in _all_routes_in_dict(update):
        connection = route_dict.get("connection")
        if connection not in catalog.CARDS:
            raise BadRequest(f"unknown connection: {connection}")
        effort = route_dict.get("effort", "")
        if effort and not supports_effort_levels(connection, route_dict.get("model", "")):
            raise BadRequest(
                f"effort '{effort}' is not supported for {connection}/{route_dict.get('model', '')}"
            )


def _merge_named(stored: dict, sent: dict | None) -> None:
    """Merge a name->route map; a None route clears that name."""
    for name, route in (sent or {}).items():
        if route is None:
            stored.pop(name, None)
        else:
            stored[name] = route


def update_routing(update: dict) -> modelrouting.Routing:
    """Merge only the fields the client sent onto the stored routing.

    ``update`` is the body dumped with exclude_unset only, so an explicit null
    is distinguishable from an absent field: it clears that route
    (`default`/`agent` sent as null, or a `tasks` entry sent as null, removes
    it) instead of leaving the stored value untouched. Returns the saved
    Routing.
    """
    # Load current routing
    stored_dict = modelrouting.load().to_dict()
    _validate_routes(update)

    # Merge: update the stored dict with only the fields that were sent.
    # A None value clears the corresponding route rather than being ignored.
    if "tasks" in update:
        _merge_named(stored_dict["tasks"], update["tasks"])
    if "agent" in update:
        stored_dict["agent"] = update["agent"]
    if "default" in update:
        stored_dict["default"] = update["default"]
    if "agent_stages" in update:
        _merge_named(stored_dict["agent_stages"], update["agent_stages"])

    # Parse back to Routing and save
    routing = modelrouting.Routing.from_dict(stored_dict)
    modelrouting.save(routing)
    _providers.reset_provider()

    # Return fresh routing
    return routing


def _all_routes_in_dict(d: dict) -> list[dict]:
    """Collect all route dicts from a routing update dict."""
    routes = []
    if "agent" in d and isinstance(d["agent"], dict):
        routes.append(d["agent"])
    if "default" in d and isinstance(d["default"], dict):
        routes.append(d["default"])
    if "tasks" in d and isinstance(d["tasks"], dict):
        for route in d["tasks"].values():
            if isinstance(route, dict):
                routes.append(route)
    if "agent_stages" in d and isinstance(d["agent_stages"], dict):
        for route in d["agent_stages"].values():
            if isinstance(route, dict):
                routes.append(route)
    return routes
