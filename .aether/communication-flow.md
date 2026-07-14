# Network Topology & Communication Map

This file visually and structurally defines how components are authorized to interact. AI agents must verify and respect these communication boundaries during implementation.

```mermaid
graph TD
    %% Node Definitions and Styling
    web-ui["Web UI <br/> <small>(FRONTEND)</small>"]
    api["API <br/> <small>(BACKEND)</small>"]
    truth-store["Truth Store <br/> <small>(BACKEND)</small>"]
    tailor-engine["Tailor Engine <br/> <small>(BACKEND)</small>"]
    guardrail-validator["Guardrail Validator <br/> <small>(BACKEND)</small>"]
    renderer["Renderer <br/> <small>(BACKEND)</small>"]
    llm-provider-layer["LLM Provider Layer <br/> <small>(BACKEND)</small>"]
    truth-data-volume["Truth Data Volume <br/> <small>(STORAGE)</small>"]
    llm-provider-service["LLM Provider Service <br/> <small>(CUSTOM)</small>"]
    cover-letter-engine["Cover Letter Engine <br/> <small>(BACKEND)</small>"]
    prompt-store["Prompt Store <br/> <small>(BACKEND)</small>"]
    secret-store["Secret Store <br/> <small>(BACKEND)</small>"]
    application-tracker["Application Tracker <br/> <small>(BACKEND)</small>"]

    %% Connection/Interaction Paths
    web-ui -->|HTTP/REST| api
    api -->|in-process| truth-store
    api -->|in-process| tailor-engine
    api -->|in-process| guardrail-validator
    api -->|in-process| renderer
    truth-store -->|in-process| llm-provider-layer
    tailor-engine -->|in-process| llm-provider-layer
    tailor-engine -->|in-process| truth-store
    guardrail-validator -->|in-process| truth-store
    truth-store -->|file I/O| truth-data-volume
    renderer -->|file I/O| truth-data-volume
    llm-provider-layer -->|HTTPS| llm-provider-service
    api -->|in-process| cover-letter-engine
    cover-letter-engine -->|in-process| llm-provider-layer
    cover-letter-engine -->|in-process| guardrail-validator
    cover-letter-engine -->|in-process| truth-store
    cover-letter-engine -->|in-process| renderer
    truth-store -->|in-process| prompt-store
    tailor-engine -->|in-process| prompt-store
    cover-letter-engine -->|in-process| prompt-store
    api -->|in-process| secret-store
    llm-provider-layer -->|in-process| secret-store
    secret-store -->|file I/O| truth-data-volume
    api -->|in-process| application-tracker
    application-tracker -->|file I/O| truth-data-volume
    application-tracker -->|in-process| renderer
```
