# SkyCargo AWB Processing — End-to-End Workflow

Private, event-driven pipeline that ingests multi-AWB PDF batches, splits them
into individual Air Waybills, runs OCR, and stores structured results — all over
private networking with managed-identity (keyless) auth.

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

    subgraph OcrStage["3 · OCR stage"]
        EG2["Event Grid system topic<br/>(filter: awb-split/…, *.pdf)"]
        Q2["Service Bus queue<br/>awb-worker-q"]
        OCRW["awb-ocr-worker<br/>(private ACA · KEDA 0–5)"]
        DI["Azure AI<br/>Document Intelligence<br/>(prebuilt-layout)"]
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
    OCRW -- "run OCR (retry + circuit breaker)" --> DI
    OCRW -- "write .json + .md" --> C3

    SPL -. "poison / corrupt PDF" .-> DLQ1
    OCRW -. "permanent error or retries exhausted" .-> DLQ2
```

## OCR worker reliability (retry → backoff → dead-letter)

```mermaid
flowchart TD
    M["Message from awb-worker-q<br/>(attempt = N)"] --> DL{"Download PDF<br/>+ run OCR"}

    DL -- success --> W["Write .json + .md<br/>to awb-output"] --> CMP["complete_message"]

    DL -- "permanent error<br/>(corrupt / non-PDF)" --> DLQ>"dead-letter<br/>reason: PermanentError"]

    DL -- "transient error /<br/>circuit open" --> CHK{"N+1 ≥ MAX_ATTEMPTS?"}
    CHK -- yes --> DLQ2>"dead-letter<br/>reason: RetriesExhausted"]
    CHK -- no --> RS["schedule_messages<br/>delay = min(BASE·2^N, MAX)<br/>attempt = N+1"] --> CMP2["complete original"]

    subgraph InCall["Inside run_ocr (per call)"]
        T["tenacity retry<br/>exponential, OCR_MAX_RETRIES"]
        CB["circuit breaker<br/>CLOSED ⇄ OPEN ⇄ HALF_OPEN"]
        T --- CB
    end
    DL -.guarded by.- InCall
```

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
    SPL2 -- "MI: SB Data Receiver" --> PE2
    OCR2 -- "MI: SB Data Receiver + Sender" --> PE2
    OCR2 -- "MI: Cognitive Services User" --> DIPE["Document Intelligence<br/>docintelligencmbc"]

    PE1 --- DNS
    PE2 --- DNS
```

## Key components

| Component | Resource | Notes |
|-----------|----------|-------|
| Input container | `awbstorageek/awb-input` | Watched by Event Grid (prefix `pdf/`). |
| Split container | `awbstorageek/awb-split` | Split outputs; watched → `awb-worker-q`. Separate container breaks recursion. |
| Output container | `awbstorageek/awb-output` | OCR `.json` + `.md`; not watched. |
| Splitter queue | `awb-sb-ek/aws-splitter-q` | Drives `awb-pdf-splitter`. |
| Worker queue | `awb-sb-ek/awb-worker-q` | Drives `awb-ocr-worker`. |
| Splitter app | `awb-pdf-splitter` (ACA) | Internal ingress, KEDA on `aws-splitter-q`. |
| OCR app | `awb-ocr-worker` (ACA) | Internal ingress, KEDA on `awb-worker-q`. |
| OCR backend | `docintelligencmbc` | Document Intelligence `prebuilt-layout`. |
| ACA environment | `cae-skycargo-internal` | VNet-injected into `vnet-ek`, internal only. |

All cross-service calls use **system-assigned managed identities** (no keys or
connection strings) and travel over **private endpoints** resolved through the
hub VNet's Private DNS zones.
