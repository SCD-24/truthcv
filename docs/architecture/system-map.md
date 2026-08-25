<!-- generated:start file:system-map -->
# System Map

```mermaid
graph TD
    agent-config["Agent Config <br/> <small>(BACKEND)</small>"]
    api["API <br/> <small>(BACKEND)</small>"]
    application-agent["Application Agent <br/> <small>(BACKEND)</small>"]
    application-tracker["Application Tracker <br/> <small>(BACKEND)</small>"]
    connections["Connections <br/> <small>(BACKEND)</small>"]
    cover-letter-engine["Cover Letter Engine <br/> <small>(BACKEND)</small>"]
    gmail-api["Gmail / Google OAuth API <br/> <small>(CUSTOM)</small>"]
    guardrail-validator["Guardrail Validator <br/> <small>(BACKEND)</small>"]
    llm-provider-layer["LLM Provider Layer <br/> <small>(BACKEND)</small>"]
    llm-provider-service["LLM Provider Service <br/> <small>(CUSTOM)</small>"]
    onboarding-store["Onboarding Store <br/> <small>(BACKEND)</small>"]
    prompt-store["Prompt Store <br/> <small>(BACKEND)</small>"]
    renderer["Renderer <br/> <small>(BACKEND)</small>"]
    screening-engine["Screening Engine <br/> <small>(BACKEND)</small>"]
    secret-store["Secret Store <br/> <small>(BACKEND)</small>"]
    tailor-engine["Tailor Engine <br/> <small>(BACKEND)</small>"]
    truth-data-volume["Truth Data Volume <br/> <small>(STORAGE)</small>"]
    truth-store["Truth Store <br/> <small>(BACKEND)</small>"]
    web-ui["Web UI <br/> <small>(FRONTEND)</small>"]
    agent-config -->|file I/O| truth-data-volume
    api -->|in-process| agent-config
    api -->|in-process| application-tracker
    api -->|in-process| connections
    api -->|in-process| cover-letter-engine
    api -->|HTTPS| gmail-api
    api -->|in-process| guardrail-validator
    api -->|in-process| onboarding-store
    api -->|in-process| renderer
    api -->|in-process| screening-engine
    api -->|in-process| secret-store
    api -->|in-process| tailor-engine
    api -->|in-process| truth-store
    application-agent -->|HTTP/REST| agent-config
    application-agent -->|HTTP/MCP (streamable HTTP JSON-RPC)| api
    application-tracker -->|in-process| renderer
    application-tracker -->|file I/O| truth-data-volume
    connections -->|HTTPS| gmail-api
    connections -->|in-process| secret-store
    cover-letter-engine -->|in-process| guardrail-validator
    cover-letter-engine -->|in-process| llm-provider-layer
    cover-letter-engine -->|in-process| prompt-store
    cover-letter-engine -->|in-process| renderer
    cover-letter-engine -->|in-process| truth-store
    guardrail-validator -->|file I/O| truth-data-volume
    guardrail-validator -->|in-process| truth-store
    llm-provider-layer -->|HTTPS| llm-provider-service
    llm-provider-layer -->|in-process| secret-store
    onboarding-store -->|file I/O| truth-data-volume
    renderer -->|file I/O| truth-data-volume
    screening-engine -->|in-process| agent-config
    screening-engine -->|in-process| application-tracker
    screening-engine -->|file I/O| truth-data-volume
    secret-store -->|file I/O| truth-data-volume
    tailor-engine -->|in-process| llm-provider-layer
    tailor-engine -->|in-process| prompt-store
    tailor-engine -->|file I/O| truth-data-volume
    tailor-engine -->|in-process| truth-store
    truth-store -->|in-process| llm-provider-layer
    truth-store -->|in-process| prompt-store
    truth-store -->|file I/O| truth-data-volume
    web-ui -->|HTTP/REST| api
```

## Components

- [Agent Config](overview.md) (`agent-config`, backend)
- [API](overview.md) (`api`, backend)
- [Application Agent](overview.md) (`application-agent`, backend)
- [Application Tracker](overview.md) (`application-tracker`, backend)
- [Connections](overview.md) (`connections`, backend)
- [Cover Letter Engine](overview.md) (`cover-letter-engine`, backend)
- [Gmail / Google OAuth API](overview.md) (`gmail-api`, custom)
- [Guardrail Validator](overview.md) (`guardrail-validator`, backend)
- [LLM Provider Layer](overview.md) (`llm-provider-layer`, backend)
- [LLM Provider Service](overview.md) (`llm-provider-service`, custom)
- [Onboarding Store](overview.md) (`onboarding-store`, backend)
- [Prompt Store](overview.md) (`prompt-store`, backend)
- [Renderer](overview.md) (`renderer`, backend)
- [Screening Engine](overview.md) (`screening-engine`, backend)
- [Secret Store](overview.md) (`secret-store`, backend)
- [Tailor Engine](overview.md) (`tailor-engine`, backend)
- [Truth Data Volume](overview.md) (`truth-data-volume`, storage)
- [Truth Store](overview.md) (`truth-store`, backend)
- [Web UI](overview.md) (`web-ui`, frontend)

## Interactions

- [agent-config → truth-data-volume](interactions/agent-config--truth-data-volume.md) via `file I/O`
- [api → agent-config](interactions/api--agent-config.md) via `in-process`
- [api → application-tracker](interactions/api--application-tracker.md) via `in-process`
- [api → connections](interactions/api--connections.md) via `in-process`
- [api → cover-letter-engine](interactions/api--cover-letter-engine.md) via `in-process`
- [api → gmail-api](interactions/api--gmail-api.md) via `HTTPS`
- [api → guardrail-validator](interactions/api--guardrail-validator.md) via `in-process`
- [api → onboarding-store](interactions/api--onboarding-store.md) via `in-process`
- [api → renderer](interactions/api--renderer.md) via `in-process`
- [api → screening-engine](interactions/api--screening-engine.md) via `in-process`
- [api → secret-store](interactions/api--secret-store.md) via `in-process`
- [api → tailor-engine](interactions/api--tailor-engine.md) via `in-process`
- [api → truth-store](interactions/api--truth-store.md) via `in-process`
- [application-agent → agent-config](interactions/application-agent--agent-config.md) via `HTTP/REST`
- [application-agent → api](interactions/application-agent--api.md) via `HTTP/MCP (streamable HTTP JSON-RPC)`
- [application-tracker → renderer](interactions/application-tracker--renderer.md) via `in-process`
- [application-tracker → truth-data-volume](interactions/application-tracker--truth-data-volume.md) via `file I/O`
- [connections → gmail-api](interactions/connections--gmail-api.md) via `HTTPS`
- [connections → secret-store](interactions/connections--secret-store.md) via `in-process`
- [cover-letter-engine → guardrail-validator](interactions/cover-letter-engine--guardrail-validator.md) via `in-process`
- [cover-letter-engine → llm-provider-layer](interactions/cover-letter-engine--llm-provider-layer.md) via `in-process`
- [cover-letter-engine → prompt-store](interactions/cover-letter-engine--prompt-store.md) via `in-process`
- [cover-letter-engine → renderer](interactions/cover-letter-engine--renderer.md) via `in-process`
- [cover-letter-engine → truth-store](interactions/cover-letter-engine--truth-store.md) via `in-process`
- [guardrail-validator → truth-data-volume](interactions/guardrail-validator--truth-data-volume.md) via `file I/O`
- [guardrail-validator → truth-store](interactions/guardrail-validator--truth-store.md) via `in-process`
- [llm-provider-layer → llm-provider-service](interactions/llm-provider-layer--llm-provider-service.md) via `HTTPS`
- [llm-provider-layer → secret-store](interactions/llm-provider-layer--secret-store.md) via `in-process`
- [onboarding-store → truth-data-volume](interactions/onboarding-store--truth-data-volume.md) via `file I/O`
- [renderer → truth-data-volume](interactions/renderer--truth-data-volume.md) via `file I/O`
- [screening-engine → agent-config](interactions/screening-engine--agent-config.md) via `in-process`
- [screening-engine → application-tracker](interactions/screening-engine--application-tracker.md) via `in-process`
- [screening-engine → truth-data-volume](interactions/screening-engine--truth-data-volume.md) via `file I/O`
- [secret-store → truth-data-volume](interactions/secret-store--truth-data-volume.md) via `file I/O`
- [tailor-engine → llm-provider-layer](interactions/tailor-engine--llm-provider-layer.md) via `in-process`
- [tailor-engine → prompt-store](interactions/tailor-engine--prompt-store.md) via `in-process`
- [tailor-engine → truth-data-volume](interactions/tailor-engine--truth-data-volume.md) via `file I/O`
- [tailor-engine → truth-store](interactions/tailor-engine--truth-store.md) via `in-process`
- [truth-store → llm-provider-layer](interactions/truth-store--llm-provider-layer.md) via `in-process`
- [truth-store → prompt-store](interactions/truth-store--prompt-store.md) via `in-process`
- [truth-store → truth-data-volume](interactions/truth-store--truth-data-volume.md) via `file I/O`
- [web-ui → api](interactions/web-ui--api.md) via `HTTP/REST`

## Groups

- [TruthCV Container (single Docker image)](groups/truthcv-container-single-docker-image.md) (`truthcv-container-single-docker-image`, 10 member(s))
<!-- generated:end file:system-map -->
