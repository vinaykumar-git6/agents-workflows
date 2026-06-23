-- =============================================================================
-- SkyCargo AWB Processing — PostgreSQL schema
-- Target server: devpostgresvinay (Microsoft.DBforPostgreSQL/flexibleServers)
--   Resource group: azure-vk-rg
--   Subscription  : 7d1e8453-2920-4f6d-9a6e-bc7005c10a22
--
-- Two objects:
--   1. awb_processing  — operational metadata for every stage of the pipeline.
--   2. awb_analytics   — flattened, denormalized table for Power BI reporting.
--
-- Pipeline stages (column `stage`):
--   awb_input   -> a multi-AWB PDF has ARRIVED (parent document).
--   awb_split   -> the PDF was SPLITTED; one row per AWB, linked to the parent.
--   awb_output  -> the split AWB PDF was OCR-PROCESSED (final output written).
--
-- Stage state (column `state`):
--   inprogress  -> work has started but not finished.
--   completed   -> stage finished successfully.
--   failed      -> stage failed (see error_detail).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Enumerated types
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'awb_stage') THEN
        CREATE TYPE awb_stage AS ENUM ('awb_input', 'awb_split', 'awb_output');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'awb_state') THEN
        CREATE TYPE awb_state AS ENUM ('inprogress', 'completed', 'failed');
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 1. Operational metadata — one row per unit of work at each stage.
--
--    * An "awb_input" row represents the parent multi-AWB PDF that arrived.
--    * Each "awb_split" row is a single Air Waybill carved out of that PDF and
--      is linked back to its parent via parent_id.
--    * An "awb_split" row transitions to / spawns its "awb_output" record once
--      OCR + normalization completes.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS awb_processing (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Logical document identity from the pipeline (claim-check docId).
    doc_id            TEXT        NOT NULL,

    -- Self-reference: split / output rows point to their parent input row.
    parent_id         BIGINT      REFERENCES awb_processing (id) ON DELETE CASCADE,

    stage             awb_stage   NOT NULL,
    state             awb_state   NOT NULL DEFAULT 'inprogress',

    -- AWB number (NULL for the parent awb_input row; set for split/output).
    awb_number        TEXT,

    -- Business metadata carried through the pipeline.
    document_name     TEXT,
    flight_number     TEXT,
    doc_date          DATE,
    source            TEXT        DEFAULT 'sharepoint',

    -- Page range this AWB occupies in the parent PDF, e.g. {0,1,2}.
    page_range        INTEGER[],

    -- Blob pointers (claim-check pattern — payload stays in storage).
    blob_url          TEXT,
    blob_name         TEXT,
    output_json_url   TEXT,
    output_md_url     TEXT,

    -- OCR / validation results (populated at the awb_output stage).
    ocr_engine        TEXT,
    ocr_confidence     NUMERIC(5, 4),
    validation_passed BOOLEAN,
    failed_check_count INTEGER     DEFAULT 0,

    -- Retry + failure diagnostics.
    attempt           INTEGER     NOT NULL DEFAULT 0,
    error_detail      TEXT,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- A given (doc_id, stage, awb_number) is unique. The parent input row has
    -- awb_number = '' so it stays distinct from its split children.
    CONSTRAINT uq_awb_processing UNIQUE (doc_id, stage, awb_number)
);

CREATE INDEX IF NOT EXISTS ix_awb_processing_parent  ON awb_processing (parent_id);
CREATE INDEX IF NOT EXISTS ix_awb_processing_stage   ON awb_processing (stage, state);
CREATE INDEX IF NOT EXISTS ix_awb_processing_awb     ON awb_processing (awb_number);
CREATE INDEX IF NOT EXISTS ix_awb_processing_docid   ON awb_processing (doc_id);
CREATE INDEX IF NOT EXISTS ix_awb_processing_created ON awb_processing (created_at);

-- Keep updated_at fresh on every UPDATE.
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_awb_processing_updated_at ON awb_processing;
CREATE TRIGGER trg_awb_processing_updated_at
    BEFORE UPDATE ON awb_processing
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- 2. Analytics table for Power BI — one row per fully processed AWB.
--
--    Denormalized & flattened so a Power BI DirectQuery / Import model can
--    slice by flight, date, engine and validation outcome without joins.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS awb_analytics (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    doc_id              TEXT        NOT NULL,
    awb_number          TEXT        NOT NULL,

    -- Business dimensions.
    document_name       TEXT,
    flight_number       TEXT,
    doc_date            DATE,
    source              TEXT,

    -- Final outcome.
    final_state         awb_state   NOT NULL,
    validation_passed   BOOLEAN,
    failed_check_count  INTEGER     DEFAULT 0,

    -- OCR quality metrics.
    ocr_engine          TEXT,
    ocr_confidence      NUMERIC(5, 4),

    -- Throughput metrics for SLA dashboards.
    page_count          INTEGER,
    retry_attempts      INTEGER     DEFAULT 0,
    received_at         TIMESTAMPTZ,
    processed_at        TIMESTAMPTZ,
    processing_seconds  NUMERIC(10, 2),

    -- Convenience date columns for Power BI time intelligence.
    processed_date      DATE        GENERATED ALWAYS AS (processed_at::date) STORED,

    output_json_url     TEXT,
    output_md_url       TEXT,

    CONSTRAINT uq_awb_analytics UNIQUE (doc_id, awb_number)
);

CREATE INDEX IF NOT EXISTS ix_awb_analytics_flight    ON awb_analytics (flight_number);
CREATE INDEX IF NOT EXISTS ix_awb_analytics_date      ON awb_analytics (doc_date);
CREATE INDEX IF NOT EXISTS ix_awb_analytics_state     ON awb_analytics (final_state);
CREATE INDEX IF NOT EXISTS ix_awb_analytics_processed ON awb_analytics (processed_date);
