<!-- generated:start file:system-map -->
# System Map

```mermaid
graph TD
    agent-config["Agent Config <br/> <small>(BACKEND)</small>"]
    api["API <br/> <small>(BACKEND)</small>"]
    application-agent["Application Agent <br/> <small>(BACKEND)</small>"]
    application-tracker["Application Tracker <br/> <small>(BACKEND)</small>"]
    browser-service["Browser Service <br/> <small>(BACKEND)</small>"]
    company-research["Company Research <br/> <small>(BACKEND)</small>"]
    connections["Connections <br/> <small>(BACKEND)</small>"]
    cover-letter-engine["Cover Letter Engine <br/> <small>(BACKEND)</small>"]
    gmail-api["Gmail / Google OAuth API <br/> <small>(CUSTOM)</small>"]
    guardrail-validator["Guardrail Validator <br/> <small>(BACKEND)</small>"]
    keyword-vocabulary["Keyword Vocabulary <br/> <small>(BACKEND)</small>"]
    llm-provider-layer["LLM Provider Layer <br/> <small>(BACKEND)</small>"]
    llm-provider-service["LLM Provider Service <br/> <small>(CUSTOM)</small>"]
    onboarding-store["Onboarding Store <br/> <small>(BACKEND)</small>"]
    prompt-store["Prompt Store <br/> <small>(BACKEND)</small>"]
    renderer["Renderer <br/> <small>(BACKEND)</small>"]
    run-store["Run Store <br/> <small>(BACKEND)</small>"]
    screening-engine["Screening Engine <br/> <small>(BACKEND)</small>"]
    secret-store["Secret Store <br/> <small>(BACKEND)</small>"]
    services-layer["Services Layer <br/> <small>(BACKEND)</small>"]
    storage-leaf["Storage <br/> <small>(BACKEND)</small>"]
    tailor-engine["Tailor Engine <br/> <small>(BACKEND)</small>"]
    truth-data-volume["Truth Data Volume <br/> <small>(STORAGE)</small>"]
    truth-store["Truth Store <br/> <small>(BACKEND)</small>"]
    web-ui["Web UI <br/> <small>(FRONTEND)</small>"]
    agent-config -->|in-process| storage-leaf
    agent-config -->|file I/O| truth-data-volume
    api -->|in-process| agent-config
    api -->|in-process| application-tracker
    api -->|WebSocket (noVNC relay) + HTTP| browser-service
    api -->|in-process| company-research
    api -->|in-process| connections
    api -->|in-process| cover-letter-engine
    api -->|HTTPS| gmail-api
    api -->|in-process| guardrail-validator
    api -->|in-process| onboarding-store
    api -->|in-process| prompt-store
    api -->|in-process| renderer
    api -->|in-process| run-store
    api -->|in-process| screening-engine
    api -->|in-process| secret-store
    api -->|in-process| services-layer
    api -->|in-process| storage-leaf
    api -->|in-process| tailor-engine
    api -->|in-process| truth-store
    application-agent -->|HTTP/REST| agent-config
    application-agent -->|HTTP/MCP (streamable HTTP JSON-RPC)| api
    application-agent -->|HTTP/MCP (streamable HTTP JSON-RPC)| browser-service
    application-agent -->|HTTPS| llm-provider-service
    application-agent -->|HTTP/MCP (streamable HTTP JSON-RPC)| run-store
    application-tracker -->|in-process| company-research
    application-tracker -->|in-process| renderer
    application-tracker -->|in-process| storage-leaf
    application-tracker -->|file I/O| truth-data-volume
    company-research -->|in-process| storage-leaf
    company-research -->|file I/O| truth-data-volume
    connections -->|HTTPS| gmail-api
    connections -->|in-process| secret-store
    cover-letter-engine -->|in-process| guardrail-validator
    cover-letter-engine -->|in-process| llm-provider-layer
    cover-letter-engine -->|in-process| prompt-store
    cover-letter-engine -->|in-process| renderer
    cover-letter-engine -->|in-process| storage-leaf
    cover-letter-engine -->|in-process| truth-store
    guardrail-validator -->|in-process| keyword-vocabulary
    guardrail-validator -->|in-process| storage-leaf
    guardrail-validator -->|in-process| truth-store
    keyword-vocabulary -->|in-process| storage-leaf
    keyword-vocabulary -->|file I/O| truth-data-volume
    llm-provider-layer -->|HTTPS| llm-provider-service
    llm-provider-layer -->|in-process| secret-store
    onboarding-store -->|in-process| storage-leaf
    onboarding-store -->|file I/O| truth-data-volume
    prompt-store -->|in-process| storage-leaf
    prompt-store -->|file I/O| truth-data-volume
    renderer -->|in-process| keyword-vocabulary
    renderer -->|in-process| prompt-store
    renderer -->|in-process| storage-leaf
    renderer -->|file I/O| truth-data-volume
    run-store -->|in-process| application-tracker
    run-store -->|in-process| screening-engine
    run-store -->|in-process| storage-leaf
    run-store -->|file I/O| truth-data-volume
    screening-engine -->|in-process| agent-config
    screening-engine -->|in-process| application-tracker
    screening-engine -->|in-process| company-research
    screening-engine -->|in-process| storage-leaf
    screening-engine -->|file I/O| truth-data-volume
    secret-store -->|in-process| storage-leaf
    secret-store -->|file I/O| truth-data-volume
    services-layer -->|in-process| agent-config
    services-layer -->|in-process| application-tracker
    services-layer -->|in-process| company-research
    services-layer -->|in-process| cover-letter-engine
    services-layer -->|in-process| guardrail-validator
    services-layer -->|in-process| llm-provider-layer
    services-layer -->|in-process| renderer
    services-layer -->|in-process| screening-engine
    services-layer -->|in-process| storage-leaf
    services-layer -->|in-process| tailor-engine
    services-layer -->|in-process| truth-store
    storage-leaf -->|file I/O| truth-data-volume
    tailor-engine -->|in-process| keyword-vocabulary
    tailor-engine -->|in-process| llm-provider-layer
    tailor-engine -->|in-process| prompt-store
    tailor-engine -->|in-process| storage-leaf
    tailor-engine -->|in-process| truth-store
    truth-store -->|in-process| llm-provider-layer
    truth-store -->|in-process| prompt-store
    truth-store -->|in-process| storage-leaf
    truth-store -->|file I/O| truth-data-volume
    web-ui -->|HTTP/REST| api
```

## Components

- [Agent Config](overview.md) (`agent-config`, backend)
- [API](overview.md) (`api`, backend)
- [Application Agent](overview.md) (`application-agent`, backend)
- [Application Tracker](overview.md) (`application-tracker`, backend)
- [Browser Service](overview.md) (`browser-service`, backend)
- [Company Research](overview.md) (`company-research`, backend)
- [Connections](overview.md) (`connections`, backend)
- [Cover Letter Engine](overview.md) (`cover-letter-engine`, backend)
- [Gmail / Google OAuth API](overview.md) (`gmail-api`, custom)
- [Guardrail Validator](overview.md) (`guardrail-validator`, backend)
- [Keyword Vocabulary](overview.md) (`keyword-vocabulary`, backend)
- [LLM Provider Layer](overview.md) (`llm-provider-layer`, backend)
- [LLM Provider Service](overview.md) (`llm-provider-service`, custom)
- [Onboarding Store](overview.md) (`onboarding-store`, backend)
- [Prompt Store](overview.md) (`prompt-store`, backend)
- [Renderer](overview.md) (`renderer`, backend)
- [Run Store](overview.md) (`run-store`, backend)
- [Screening Engine](overview.md) (`screening-engine`, backend)
- [Secret Store](overview.md) (`secret-store`, backend)
- [Services Layer](overview.md) (`services-layer`, backend)
- [Storage](overview.md) (`storage-leaf`, backend)
- [Tailor Engine](overview.md) (`tailor-engine`, backend)
- [Truth Data Volume](overview.md) (`truth-data-volume`, storage)
- [Truth Store](overview.md) (`truth-store`, backend)
- [Web UI](overview.md) (`web-ui`, frontend)

## Interactions

- [agent-config → storage-leaf](interactions/agent-config--storage-leaf.md) via `in-process`
- [agent-config → truth-data-volume](interactions/agent-config--truth-data-volume.md) via `file I/O`
- [api → agent-config](interactions/api--agent-config.md) via `in-process`
- [api → application-tracker](interactions/api--application-tracker.md) via `in-process`
- [api → browser-service](interactions/api--browser-service.md) via `WebSocket (noVNC relay) + HTTP`
- [api → company-research](interactions/api--company-research.md) via `in-process`
- [api → connections](interactions/api--connections.md) via `in-process`
- [api → cover-letter-engine](interactions/api--cover-letter-engine.md) via `in-process`
- [api → gmail-api](interactions/api--gmail-api.md) via `HTTPS`
- [api → guardrail-validator](interactions/api--guardrail-validator.md) via `in-process`
- [api → onboarding-store](interactions/api--onboarding-store.md) via `in-process`
- [api → prompt-store](interactions/api--prompt-store.md) via `in-process`
- [api → renderer](interactions/api--renderer.md) via `in-process`
- [api → run-store](interactions/api--run-store.md) via `in-process`
- [api → screening-engine](interactions/api--screening-engine.md) via `in-process`
- [api → secret-store](interactions/api--secret-store.md) via `in-process`
- [api → services-layer](interactions/api--services-layer.md) via `in-process`
- [api → storage-leaf](interactions/api--storage-leaf.md) via `in-process`
- [api → tailor-engine](interactions/api--tailor-engine.md) via `in-process`
- [api → truth-store](interactions/api--truth-store.md) via `in-process`
- [application-agent → agent-config](interactions/application-agent--agent-config.md) via `HTTP/REST`
- [application-agent → api](interactions/application-agent--api.md) via `HTTP/MCP (streamable HTTP JSON-RPC)`
- [application-agent → browser-service](interactions/application-agent--browser-service.md) via `HTTP/MCP (streamable HTTP JSON-RPC)`
- [application-agent → llm-provider-service](interactions/application-agent--llm-provider-service.md) via `HTTPS`
- [application-agent → run-store](interactions/application-agent--run-store.md) via `HTTP/MCP (streamable HTTP JSON-RPC)`
- [application-tracker → company-research](interactions/application-tracker--company-research.md) via `in-process`
- [application-tracker → renderer](interactions/application-tracker--renderer.md) via `in-process`
- [application-tracker → storage-leaf](interactions/application-tracker--storage-leaf.md) via `in-process`
- [application-tracker → truth-data-volume](interactions/application-tracker--truth-data-volume.md) via `file I/O`
- [company-research → storage-leaf](interactions/company-research--storage-leaf.md) via `in-process`
- [company-research → truth-data-volume](interactions/company-research--truth-data-volume.md) via `file I/O`
- [connections → gmail-api](interactions/connections--gmail-api.md) via `HTTPS`
- [connections → secret-store](interactions/connections--secret-store.md) via `in-process`
- [cover-letter-engine → guardrail-validator](interactions/cover-letter-engine--guardrail-validator.md) via `in-process`
- [cover-letter-engine → llm-provider-layer](interactions/cover-letter-engine--llm-provider-layer.md) via `in-process`
- [cover-letter-engine → prompt-store](interactions/cover-letter-engine--prompt-store.md) via `in-process`
- [cover-letter-engine → renderer](interactions/cover-letter-engine--renderer.md) via `in-process`
- [cover-letter-engine → storage-leaf](interactions/cover-letter-engine--storage-leaf.md) via `in-process`
- [cover-letter-engine → truth-store](interactions/cover-letter-engine--truth-store.md) via `in-process`
- [guardrail-validator → keyword-vocabulary](interactions/guardrail-validator--keyword-vocabulary.md) via `in-process`
- [guardrail-validator → storage-leaf](interactions/guardrail-validator--storage-leaf.md) via `in-process`
- [guardrail-validator → truth-store](interactions/guardrail-validator--truth-store.md) via `in-process`
- [keyword-vocabulary → storage-leaf](interactions/keyword-vocabulary--storage-leaf.md) via `in-process`
- [keyword-vocabulary → truth-data-volume](interactions/keyword-vocabulary--truth-data-volume.md) via `file I/O`
- [llm-provider-layer → llm-provider-service](interactions/llm-provider-layer--llm-provider-service.md) via `HTTPS`
- [llm-provider-layer → secret-store](interactions/llm-provider-layer--secret-store.md) via `in-process`
- [onboarding-store → storage-leaf](interactions/onboarding-store--storage-leaf.md) via `in-process`
- [onboarding-store → truth-data-volume](interactions/onboarding-store--truth-data-volume.md) via `file I/O`
- [prompt-store → storage-leaf](interactions/prompt-store--storage-leaf.md) via `in-process`
- [prompt-store → truth-data-volume](interactions/prompt-store--truth-data-volume.md) via `file I/O`
- [renderer → keyword-vocabulary](interactions/renderer--keyword-vocabulary.md) via `in-process`
- [renderer → prompt-store](interactions/renderer--prompt-store.md) via `in-process`
- [renderer → storage-leaf](interactions/renderer--storage-leaf.md) via `in-process`
- [renderer → truth-data-volume](interactions/renderer--truth-data-volume.md) via `file I/O`
- [run-store → application-tracker](interactions/run-store--application-tracker.md) via `in-process`
- [run-store → screening-engine](interactions/run-store--screening-engine.md) via `in-process`
- [run-store → storage-leaf](interactions/run-store--storage-leaf.md) via `in-process`
- [run-store → truth-data-volume](interactions/run-store--truth-data-volume.md) via `file I/O`
- [screening-engine → agent-config](interactions/screening-engine--agent-config.md) via `in-process`
- [screening-engine → application-tracker](interactions/screening-engine--application-tracker.md) via `in-process`
- [screening-engine → company-research](interactions/screening-engine--company-research.md) via `in-process`
- [screening-engine → storage-leaf](interactions/screening-engine--storage-leaf.md) via `in-process`
- [screening-engine → truth-data-volume](interactions/screening-engine--truth-data-volume.md) via `file I/O`
- [secret-store → storage-leaf](interactions/secret-store--storage-leaf.md) via `in-process`
- [secret-store → truth-data-volume](interactions/secret-store--truth-data-volume.md) via `file I/O`
- [services-layer → agent-config](interactions/services-layer--agent-config.md) via `in-process`
- [services-layer → application-tracker](interactions/services-layer--application-tracker.md) via `in-process`
- [services-layer → company-research](interactions/services-layer--company-research.md) via `in-process`
- [services-layer → cover-letter-engine](interactions/services-layer--cover-letter-engine.md) via `in-process`
- [services-layer → guardrail-validator](interactions/services-layer--guardrail-validator.md) via `in-process`
- [services-layer → llm-provider-layer](interactions/services-layer--llm-provider-layer.md) via `in-process`
- [services-layer → renderer](interactions/services-layer--renderer.md) via `in-process`
- [services-layer → screening-engine](interactions/services-layer--screening-engine.md) via `in-process`
- [services-layer → storage-leaf](interactions/services-layer--storage-leaf.md) via `in-process`
- [services-layer → tailor-engine](interactions/services-layer--tailor-engine.md) via `in-process`
- [services-layer → truth-store](interactions/services-layer--truth-store.md) via `in-process`
- [storage-leaf → truth-data-volume](interactions/storage-leaf--truth-data-volume.md) via `file I/O`
- [tailor-engine → keyword-vocabulary](interactions/tailor-engine--keyword-vocabulary.md) via `in-process`
- [tailor-engine → llm-provider-layer](interactions/tailor-engine--llm-provider-layer.md) via `in-process`
- [tailor-engine → prompt-store](interactions/tailor-engine--prompt-store.md) via `in-process`
- [tailor-engine → storage-leaf](interactions/tailor-engine--storage-leaf.md) via `in-process`
- [tailor-engine → truth-store](interactions/tailor-engine--truth-store.md) via `in-process`
- [truth-store → llm-provider-layer](interactions/truth-store--llm-provider-layer.md) via `in-process`
- [truth-store → prompt-store](interactions/truth-store--prompt-store.md) via `in-process`
- [truth-store → storage-leaf](interactions/truth-store--storage-leaf.md) via `in-process`
- [truth-store → truth-data-volume](interactions/truth-store--truth-data-volume.md) via `file I/O`
- [web-ui → api](interactions/web-ui--api.md) via `HTTP/REST`

## Groups

- [TruthCV Container (single Docker image)](groups/truthcv-container-single-docker-image.md) (`truthcv-container-single-docker-image`, 15 member(s))
<!-- generated:end file:system-map -->
