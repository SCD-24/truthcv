<!-- generated:start file:system-map -->
> These architecture docs are **not verified at the current commit** (no full drift sweep has run yet). Treat them as a snapshot and verify against source before relying on them.

# System Map

```mermaid
graph TD
    api["API <br/> <small>(BACKEND)</small>"]
    application-tracker["Application Tracker <br/> <small>(BACKEND)</small>"]
    cover-letter-engine["Cover Letter Engine <br/> <small>(BACKEND)</small>"]
    guardrail-validator["Guardrail Validator <br/> <small>(BACKEND)</small>"]
    llm-provider-layer["LLM Provider Layer <br/> <small>(BACKEND)</small>"]
    llm-provider-service["LLM Provider Service <br/> <small>(CUSTOM)</small>"]
    prompt-store["Prompt Store <br/> <small>(BACKEND)</small>"]
    renderer["Renderer <br/> <small>(BACKEND)</small>"]
    secret-store["Secret Store <br/> <small>(BACKEND)</small>"]
    tailor-engine["Tailor Engine <br/> <small>(BACKEND)</small>"]
    truth-data-volume["Truth Data Volume <br/> <small>(STORAGE)</small>"]
    truth-store["Truth Store <br/> <small>(BACKEND)</small>"]
    web-ui["Web UI <br/> <small>(FRONTEND)</small>"]
    api -->|in-process| application-tracker
    api -->|in-process| cover-letter-engine
    api -->|in-process| guardrail-validator
    api -->|in-process| renderer
    api -->|in-process| secret-store
    api -->|in-process| tailor-engine
    api -->|in-process| truth-store
    application-tracker -->|in-process| renderer
    application-tracker -->|file I/O| truth-data-volume
    cover-letter-engine -->|in-process| guardrail-validator
    cover-letter-engine -->|in-process| llm-provider-layer
    cover-letter-engine -->|in-process| prompt-store
    cover-letter-engine -->|in-process| renderer
    cover-letter-engine -->|in-process| truth-store
    guardrail-validator -->|in-process| truth-store
    llm-provider-layer -->|HTTPS| llm-provider-service
    llm-provider-layer -->|in-process| secret-store
    renderer -->|file I/O| truth-data-volume
    secret-store -->|file I/O| truth-data-volume
    tailor-engine -->|in-process| llm-provider-layer
    tailor-engine -->|in-process| prompt-store
    tailor-engine -->|in-process| truth-store
    truth-store -->|in-process| llm-provider-layer
    truth-store -->|in-process| prompt-store
    truth-store -->|file I/O| truth-data-volume
    web-ui -->|HTTP/REST| api
```

## Components

- [API](overview.md) (`api`, backend)
- [Application Tracker](overview.md) (`application-tracker`, backend)
- [Cover Letter Engine](overview.md) (`cover-letter-engine`, backend)
- [Guardrail Validator](overview.md) (`guardrail-validator`, backend)
- [LLM Provider Layer](overview.md) (`llm-provider-layer`, backend)
- [LLM Provider Service](overview.md) (`llm-provider-service`, custom)
- [Prompt Store](overview.md) (`prompt-store`, backend)
- [Renderer](overview.md) (`renderer`, backend)
- [Secret Store](overview.md) (`secret-store`, backend)
- [Tailor Engine](overview.md) (`tailor-engine`, backend)
- [Truth Data Volume](overview.md) (`truth-data-volume`, storage)
- [Truth Store](overview.md) (`truth-store`, backend)
- [Web UI](overview.md) (`web-ui`, frontend)

## Interactions

- [api → application-tracker](interactions/api--application-tracker.md) via `in-process`
- [api → cover-letter-engine](interactions/api--cover-letter-engine.md) via `in-process`
- [api → guardrail-validator](interactions/api--guardrail-validator.md) via `in-process`
- [api → renderer](interactions/api--renderer.md) via `in-process`
- [api → secret-store](interactions/api--secret-store.md) via `in-process`
- [api → tailor-engine](interactions/api--tailor-engine.md) via `in-process`
- [api → truth-store](interactions/api--truth-store.md) via `in-process`
- [application-tracker → renderer](interactions/application-tracker--renderer.md) via `in-process`
- [application-tracker → truth-data-volume](interactions/application-tracker--truth-data-volume.md) via `file I/O`
- [cover-letter-engine → guardrail-validator](interactions/cover-letter-engine--guardrail-validator.md) via `in-process`
- [cover-letter-engine → llm-provider-layer](interactions/cover-letter-engine--llm-provider-layer.md) via `in-process`
- [cover-letter-engine → prompt-store](interactions/cover-letter-engine--prompt-store.md) via `in-process`
- [cover-letter-engine → renderer](interactions/cover-letter-engine--renderer.md) via `in-process`
- [cover-letter-engine → truth-store](interactions/cover-letter-engine--truth-store.md) via `in-process`
- [guardrail-validator → truth-store](interactions/guardrail-validator--truth-store.md) via `in-process`
- [llm-provider-layer → llm-provider-service](interactions/llm-provider-layer--llm-provider-service.md) via `HTTPS`
- [llm-provider-layer → secret-store](interactions/llm-provider-layer--secret-store.md) via `in-process`
- [renderer → truth-data-volume](interactions/renderer--truth-data-volume.md) via `file I/O`
- [secret-store → truth-data-volume](interactions/secret-store--truth-data-volume.md) via `file I/O`
- [tailor-engine → llm-provider-layer](interactions/tailor-engine--llm-provider-layer.md) via `in-process`
- [tailor-engine → prompt-store](interactions/tailor-engine--prompt-store.md) via `in-process`
- [tailor-engine → truth-store](interactions/tailor-engine--truth-store.md) via `in-process`
- [truth-store → llm-provider-layer](interactions/truth-store--llm-provider-layer.md) via `in-process`
- [truth-store → prompt-store](interactions/truth-store--prompt-store.md) via `in-process`
- [truth-store → truth-data-volume](interactions/truth-store--truth-data-volume.md) via `file I/O`
- [web-ui → api](interactions/web-ui--api.md) via `HTTP/REST`

## Groups

- [TruthCV Container (single Docker image)](groups/truthcv-container-single-docker-image.md) (`truthcv-container-single-docker-image`, 12 member(s))
<!-- generated:end file:system-map -->
