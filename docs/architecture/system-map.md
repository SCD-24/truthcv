<!-- generated:start file:system-map -->
# System Map

```mermaid
graph TD
    api["API <br/> <small>(BACKEND)</small>"]
    application-agent["Application Agent <br/> <small>(BACKEND)</small>"]
    application-pipeline["Application Pipeline <br/> <small>(BACKEND)</small>"]
    arbeitnow-api["Arbeitnow Job Board API <br/> <small>(CUSTOM)</small>"]
    browser-service["Browser Service <br/> <small>(BACKEND)</small>"]
    document-generation["Document Generation <br/> <small>(BACKEND)</small>"]
    gmail-api["Gmail / Google OAuth API <br/> <small>(CUSTOM)</small>"]
    guardrail-validator["Guardrail Validator <br/> <small>(BACKEND)</small>"]
    integrations["Integrations <br/> <small>(BACKEND)</small>"]
    jev-api["Jev (TypeSafe System One) API <br/> <small>(CUSTOM)</small>"]
    llm-provider-layer["LLM Provider Layer <br/> <small>(BACKEND)</small>"]
    llm-provider-service["LLM Provider Service <br/> <small>(CUSTOM)</small>"]
    orchestration["Orchestration <br/> <small>(BACKEND)</small>"]
    secret-store["Secret Store <br/> <small>(BACKEND)</small>"]
    storage["Storage & Shared Leaves <br/> <small>(BACKEND)</small>"]
    truth-data-volume["Truth Data Volume <br/> <small>(STORAGE)</small>"]
    truth-store["Truth Store <br/> <small>(BACKEND)</small>"]
    web-ui["Web UI <br/> <small>(FRONTEND)</small>"]
    api -->|WebSocket (noVNC relay) + HTTP| browser-service
    api -->|in-process| orchestration
    application-agent -->|HTTP/MCP (streamable HTTP JSON-RPC)| api
    application-agent -->|HTTP/MCP (streamable HTTP JSON-RPC)| browser-service
    application-agent -->|HTTPS| llm-provider-service
    application-pipeline -->|in-process| document-generation
    application-pipeline -->|HTTPS| jev-api
    application-pipeline -->|in-process| storage
    document-generation -->|in-process| guardrail-validator
    document-generation -->|in-process| llm-provider-layer
    document-generation -->|in-process| storage
    document-generation -->|in-process| truth-store
    guardrail-validator -->|in-process| storage
    guardrail-validator -->|in-process| truth-store
    integrations -->|in-process| application-pipeline
    integrations -->|HTTPS| arbeitnow-api
    integrations -->|HTTPS| gmail-api
    integrations -->|HTTPS| jev-api
    integrations -->|in-process| secret-store
    integrations -->|in-process| storage
    llm-provider-layer -->|HTTPS| llm-provider-service
    llm-provider-layer -->|in-process| secret-store
    orchestration -->|HTTP/REST| application-agent
    orchestration -->|in-process| application-pipeline
    orchestration -->|HTTP| browser-service
    orchestration -->|in-process| document-generation
    orchestration -->|in-process| guardrail-validator
    orchestration -->|in-process| integrations
    orchestration -->|in-process| llm-provider-layer
    orchestration -->|in-process| secret-store
    orchestration -->|in-process| storage
    orchestration -->|in-process| truth-store
    secret-store -->|in-process| storage
    storage -->|file I/O| truth-data-volume
    truth-store -->|in-process| storage
    web-ui -->|HTTP/REST| api
```

## Components

- [API](overview.md) (`api`, backend)
- [Application Agent](overview.md) (`application-agent`, backend)
- [Application Pipeline](overview.md) (`application-pipeline`, backend)
- [Arbeitnow Job Board API](overview.md) (`arbeitnow-api`, custom)
- [Browser Service](overview.md) (`browser-service`, backend)
- [Document Generation](overview.md) (`document-generation`, backend)
- [Gmail / Google OAuth API](overview.md) (`gmail-api`, custom)
- [Guardrail Validator](overview.md) (`guardrail-validator`, backend)
- [Integrations](overview.md) (`integrations`, backend)
- [Jev (TypeSafe System One) API](overview.md) (`jev-api`, custom)
- [LLM Provider Layer](overview.md) (`llm-provider-layer`, backend)
- [LLM Provider Service](overview.md) (`llm-provider-service`, custom)
- [Orchestration](overview.md) (`orchestration`, backend)
- [Secret Store](overview.md) (`secret-store`, backend)
- [Storage & Shared Leaves](overview.md) (`storage`, backend)
- [Truth Data Volume](overview.md) (`truth-data-volume`, storage)
- [Truth Store](overview.md) (`truth-store`, backend)
- [Web UI](overview.md) (`web-ui`, frontend)

## Interactions

- [api → browser-service](interactions/api--browser-service.md) via `WebSocket (noVNC relay) + HTTP`
- [api → orchestration](interactions/api--orchestration.md) via `in-process`
- [application-agent → api](interactions/application-agent--api.md) via `HTTP/MCP (streamable HTTP JSON-RPC)`
- [application-agent → browser-service](interactions/application-agent--browser-service.md) via `HTTP/MCP (streamable HTTP JSON-RPC)`
- [application-agent → llm-provider-service](interactions/application-agent--llm-provider-service.md) via `HTTPS`
- [application-pipeline → document-generation](interactions/application-pipeline--document-generation.md) via `in-process`
- [application-pipeline → jev-api](interactions/application-pipeline--jev-api.md) via `HTTPS`
- [application-pipeline → storage](interactions/application-pipeline--storage.md) via `in-process`
- [document-generation → guardrail-validator](interactions/document-generation--guardrail-validator.md) via `in-process`
- [document-generation → llm-provider-layer](interactions/document-generation--llm-provider-layer.md) via `in-process`
- [document-generation → storage](interactions/document-generation--storage.md) via `in-process`
- [document-generation → truth-store](interactions/document-generation--truth-store.md) via `in-process`
- [guardrail-validator → storage](interactions/guardrail-validator--storage.md) via `in-process`
- [guardrail-validator → truth-store](interactions/guardrail-validator--truth-store.md) via `in-process`
- [integrations → application-pipeline](interactions/integrations--application-pipeline.md) via `in-process`
- [integrations → arbeitnow-api](interactions/integrations--arbeitnow-api.md) via `HTTPS`
- [integrations → gmail-api](interactions/integrations--gmail-api.md) via `HTTPS`
- [integrations → jev-api](interactions/integrations--jev-api.md) via `HTTPS`
- [integrations → secret-store](interactions/integrations--secret-store.md) via `in-process`
- [integrations → storage](interactions/integrations--storage.md) via `in-process`
- [llm-provider-layer → llm-provider-service](interactions/llm-provider-layer--llm-provider-service.md) via `HTTPS`
- [llm-provider-layer → secret-store](interactions/llm-provider-layer--secret-store.md) via `in-process`
- [orchestration → application-agent](interactions/orchestration--application-agent.md) via `HTTP/REST`
- [orchestration → application-pipeline](interactions/orchestration--application-pipeline.md) via `in-process`
- [orchestration → browser-service](interactions/orchestration--browser-service.md) via `HTTP`
- [orchestration → document-generation](interactions/orchestration--document-generation.md) via `in-process`
- [orchestration → guardrail-validator](interactions/orchestration--guardrail-validator.md) via `in-process`
- [orchestration → integrations](interactions/orchestration--integrations.md) via `in-process`
- [orchestration → llm-provider-layer](interactions/orchestration--llm-provider-layer.md) via `in-process`
- [orchestration → secret-store](interactions/orchestration--secret-store.md) via `in-process`
- [orchestration → storage](interactions/orchestration--storage.md) via `in-process`
- [orchestration → truth-store](interactions/orchestration--truth-store.md) via `in-process`
- [secret-store → storage](interactions/secret-store--storage.md) via `in-process`
- [storage → truth-data-volume](interactions/storage--truth-data-volume.md) via `file I/O`
- [truth-store → storage](interactions/truth-store--storage.md) via `in-process`
- [web-ui → api](interactions/web-ui--api.md) via `HTTP/REST`

## Groups

- [Agent Runtime (sibling containers)](groups/agent-runtime-sibling-containers.md) (`agent-runtime-sibling-containers`, 2 member(s))
- [External Services](groups/external-services.md) (`external-services`, 4 member(s))
- [TruthCV Container (single Docker image)](groups/truthcv-container-single-docker-image.md) (`truthcv-container-single-docker-image`, 11 member(s))
<!-- generated:end file:system-map -->
