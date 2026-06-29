# SkyCargo AWB Processing — End-to-End Workflow

Private, event-driven pipeline that ingests multi-AWB PDF batches, splits them
into individual Air Waybills, runs OCR, normalizes the result with a Microsoft
Agent Framework workflow, stores structured output, and persists per-stage
metadata to PostgreSQL — all over private networking with managed-identity
(keyless) auth.

## Pipeline overview

```mermaid
flowchart TD
    subgraph Ingest["1 · Ingest"]
        U[/"PDF batch uploaded<br/>awb-input/pdf/&lt;timestamp&gt;/&lt;file&gt;.pdf"/]
    end

    subgraph SplitStage["2 · Split stage"]
        EG1["Event Grid system topic<br/>(filter: pdf/…, *.pdf)"]
        Q1["Service Bus queue<br/>aws-splitter-q"]
        SPL["awb-pdf-splitter<br/>(private ACA · KEDA 0–5)"]
    end

    subgraph OcrStage["3 · OCR + normalization stage"]
        EG2["Event Grid system topic<br/>(filter: awb-split/…, *.pdf)"]
        Q2["Service Bus queue<br/>awb-worker-q"]
        OCRW["awb-ocr-worker<br/>(private ACA · KEDA 0–5)"]
        DI["Azure AI<br/>Document Intelligence<br/>(prebuilt-layout)"]
        AGENT["AWB agent<br/>Foundry · gpt-5.4<br/>(deterministic)"]
    end

    subgraph DbStage["4 · Metadata persistence stage"]
        QDB["Service Bus queue<br/>async-db-update-q"]
        DBU["awb-db-updater<br/>(private ACA)"]
        PG[("PostgreSQL<br/>devpostgresvinay<br/>schema: skycargo")]
    end

    subgraph Storage["Blob Storage · awbstorageek"]
        C1[("awb-input")]
        C2[("awb-split")]
        C3[("awb-output")]
    end

    DLQ1>"aws-splitter-q<br/>dead-letter"]
    DLQ2>"awb-worker-q<br/>dead-letter"]

    U --> C1
    C1 -- BlobCreated --> EG1 --> Q1 --> SPL
    SPL -- "download PDF (MI)" --> C1
    SPL -- "split per AWB → upload" --> C2

    C2 -- BlobCreated --> EG2 --> Q2 --> OCRW
    OCRW -- "download split PDF (MI)" --> C2
    OCRW -- "OcrExecutor: run OCR (retry + circuit breaker)" --> DI
    OCRW -- "AwbFormatterExecutor: normalize → AWB JSON (MI)" --> AGENT
    OCRW -- "write .json (agent) + .md (OCR)" --> C3

    SPL -- "publish stage events (MI)" --> QDB
    OCRW -- "publish stage events (MI)" --> QDB
    QDB --> DBU -- "upsert rows (MI)" --> PG

    SPL -. "poison / corrupt PDF" .-> DLQ1
    OCRW -. "permanent error or retries exhausted" .-> DLQ2
```

## OCR worker — sequential agent orchestration

Inside the worker, each message runs a Microsoft Agent Framework workflow that
chains two executors with a single sequential edge. The agent is configured for
deterministic output (low temperature + fixed seed + structured output), so the
same OCR text always yields identical normalized JSON.

```mermaid
flowchart LR
    REQ[/"OcrRequest<br/>(pdf_bytes, source_name)"/] --> OE

    subgraph WF["WorkflowBuilder · sequential"]
        OE["OcrExecutor<br/>app/executors/ocr_executor.py"]
        FE["AwbFormatterExecutor<br/>app/executors/formatter_executor.py"]
        OE -- "OcrPayload(text, markdown)" --> FE
    end

    OE -- "services/ocr.run_ocr()" --> DI["Document Intelligence"]
    FE -- "agent.run(response_format=AwbDocument)" --> AG["Foundry agent · gpt-5.4"]
    FE --> OUT[/"FormattedResult<br/>json_text (AWB) + markdown (OCR)"/]
    OUT --> UP["services/storage.upload_outputs<br/>.json = normalized AWB · .md = OCR"]
```

## OCR worker reliability (retry → backoff → dead-letter)

```mermaid
flowchart TD
    M["Message from awb-worker-q<br/>(attempt = N)"] --> DL{"Download PDF<br/>+ run orchestration"}

    DL -- success --> W["Write .json (AWB agent)<br/>+ .md (OCR) to awb-output"] --> CMP["complete_message"]

    DL -- "permanent error<br/>(corrupt / non-PDF)" --> DLQ>"dead-letter<br/>reason: PermanentError"]

    DL -- "transient error /<br/>circuit open" --> CHK{"N+1 ≥ MAX_ATTEMPTS?"}
    CHK -- yes --> DLQ2>"dead-letter<br/>reason: RetriesExhausted"]
    CHK -- no --> RS["schedule_messages<br/>delay = min(BASE·2^N, MAX)<br/>attempt = N+1"] --> CMP2["complete original"]

    subgraph InCall["Inside OcrExecutor → services/ocr.run_ocr (per call)"]
        T["tenacity retry<br/>exponential, OCR_MAX_RETRIES"]
        CB["circuit breaker<br/>CLOSED ⇄ OPEN ⇄ HALF_OPEN"]
        T --- CB
    end
    DL -.guarded by.- InCall
```

## Metadata persistence (async DB updates)

The splitter and the OCR worker **publish stage/state events** to the
`async-db-update-q` Service Bus queue (keyless, managed identity) at each
lifecycle transition. The dedicated `awb-db-updater` worker consumes that queue
and upserts rows into the `skycargo` PostgreSQL schema — decoupling the
processing path from the database so a DB hiccup never blocks OCR or splitting.

```mermaid
flowchart TD
    SPL["awb-pdf-splitter"] -- "awb_input: inprogress/completed/failed<br/>awb_split: completed (per AWB)" --> Q["async-db-update-q"]
    OCR["awb-ocr-worker"] -- "awb_output: inprogress/completed/failed" --> Q
    Q --> DBU["awb-db-updater (private ACA)"]
    DBU -- "every message" --> T1[("skycargo.awb_processing")]
    DBU -- "awb_output + completed/failed" --> T2[("skycargo.awb_analytics (Power BI)")]
```

- A stable `docId` (`pdf/<timestamp>`, derived from the source blob path) is
  shared by both producers so split/output rows link back to their `awb_input`
  parent via `parent_id`.
- Publishing is **best-effort**: a publish failure is logged but never breaks
  the pipeline.
- See [`awb-db-updater/README.md`](awb-db-updater/README.md) for the full
  message contract and schema.

## Networking & identity

```mermaid
flowchart LR
    subgraph VNetEK["vnet-ek (10.10.0.0/16) · emirates-ai-usecase"]
        ACAENV["ACA env<br/>cae-skycargo-internal<br/>(internal, VNet-injected)"]
        SPL2["awb-pdf-splitter"]
        OCR2["awb-ocr-worker"]
        ACAENV --- SPL2
        ACAENV --- OCR2
    end

    subgraph VNetHub["vnet-hub · azure-vk-hub"]
        DNS["Private DNS zones<br/>privatelink.blob.core.windows.net<br/>privatelink.servicebus.windows.net"]
    end

    VNetEK <-- "VNet peering (Connected)" --> VNetHub

    PE1["Private Endpoint<br/>pe-awb-blob"]
    PE2["Private Endpoint<br/>pe-awb-servicebus"]

    SPL2 -- "MI: Blob Data Contributor" --> PE1
    OCR2 -- "MI: Blob Data Contributor" --> PE1
    SPL2 -- "MI: SB Data Receiver + Sender" --> PE2
    OCR2 -- "MI: SB Data Receiver + Sender" --> PE2
    OCR2 -- "MI: Cognitive Services User" --> DIPE["Document Intelligence<br/>docintelligencmbc"]
    OCR2 -- "MI: Cognitive Services OpenAI User" --> FNDRY["Foundry (AI Services)<br/>mydevfoundry0603 · gpt-5.4"]

    PE1 --- DNS
    PE2 --- DNS
```

## Key components

| Component | Resource | Notes |
|-----------|----------|-------|
| Input container | `awbstorageek/awb-input` | Watched by Event Grid (prefix `pdf/`). |
| Split container | `awbstorageek/awb-split` | Split outputs; watched → `awb-worker-q`. Separate container breaks recursion. |
| Output container | `awbstorageek/awb-output` | Normalized AWB `.json` (agent) + OCR `.md`; not watched. |
| Splitter queue | `awb-sb-ek/aws-splitter-q` | Drives `awb-pdf-splitter`. |
| Worker queue | `awb-sb-ek/awb-worker-q` | Drives `awb-ocr-worker`. |
| DB-update queue | `awb-sb-ek/async-db-update-q` | Stage/state events from splitter + worker; drives `awb-db-updater`. |
| Splitter app | `awb-pdf-splitter` (ACA) | Internal ingress, KEDA on `aws-splitter-q`. |
| OCR app | `awb-ocr-worker` (ACA) | Internal ingress, KEDA on `awb-worker-q`. |
| DB updater app | `awb-db-updater` (ACA) | Consumes `async-db-update-q`, upserts `skycargo` schema. |
| OCR backend | `docintelligencmbc` | Document Intelligence `prebuilt-layout`. |
| AWB agent model | `mydevfoundry0603` | Foundry `gpt-5.4`; deterministic normalization. |
| Metadata store | `devpostgresvinay` | PostgreSQL flexible server, schema `skycargo` (`awb_processing`, `awb_analytics`). |
| ACA environment | `cae-skycargo-internal` | VNet-injected into `vnet-ek`, internal only. |

All cross-service calls use **system-assigned managed identities** (no keys or
connection strings) and travel over **private endpoints** resolved through the
hub VNet's Private DNS zones.

## OCR worker code structure

The worker is a production-grade Python package (`app/`) with clear separation
between services, executors, and orchestration:

```
awb-ocr-worker/
  Dockerfile                      # non-root, healthcheck, runs app.main:app
  requirements.txt
  app/
    main.py                       # FastAPI health API; starts the consumer
    consumer.py                   # Service Bus loop: retry → backoff → dead-letter
    core/
      circuit_breaker.py          # thread-safe CLOSED/OPEN/HALF_OPEN breaker
    services/
      ocr.py                      # Document Intelligence (retry + breaker)
      storage.py                  # Blob download + upload_outputs(.json/.md)
      db_events.py                # publish awb_output events to async-db-update-q
    executors/
      ocr_executor.py             # OcrExecutor: PDF → OCR text + markdown
      formatter_executor.py       # AwbFormatterExecutor: text → normalized JSON
    orchestration/
      orchestrator.py             # sequential WorkflowBuilder wiring + run_orchestration
      agent.py                    # Foundry chat agent factory + instructions
      schema.py                   # AwbDocument / Party / RoutingLeg pydantic models
      messages.py                 # OcrRequest / OcrPayload / FormattedResult
```
