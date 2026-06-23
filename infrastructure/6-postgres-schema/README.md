# 6 — PostgreSQL schema (AWB metadata + Power BI analytics)

Schema for the SkyCargo AWB pipeline on the existing Flexible Server:

```
/subscriptions/7d1e8453-2920-4f6d-9a6e-bc7005c10a22/resourceGroups/azure-vk-rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/devpostgresvinay
```

## Tables

| Table | Purpose |
|-------|---------|
| `awb_processing` | Operational metadata for **every stage**. One row per unit of work. |
| `awb_analytics`  | Flattened, denormalized table for **Power BI** (one row per processed AWB). |

### `awb_processing` lifecycle

| `stage` | Meaning | Rows |
|---------|---------|------|
| `awb_input`  | Multi-AWB PDF **arrived** | 1 parent row (`awb_number = ''`) |
| `awb_split`  | PDF **splitted** | 1 row **per AWB**, linked to parent via `parent_id` |
| `awb_output` | AWB **OCR-processed** | 1 row per AWB output, linked via `parent_id` |

Each row carries a `state`: `inprogress` → `completed` / `failed` (with `error_detail`).

## Deploy

Connect with Entra ID (passwordless) — matches the worker's auth model:

```bash
# Acquire an access token for PostgreSQL
export PGPASSWORD=$(az account get-access-token \
  --resource-type oss-rdbms \
  --query accessToken -o tsv)

psql "host=devpostgresvinay.postgres.database.azure.com \
      port=5432 \
      dbname=postgres \
      user=$(az account show --query user.name -o tsv) \
      sslmode=require" \
  -f schema.sql
```

> Ensure your client IP is allowed on the server firewall and that your Entra
> principal is added as a PostgreSQL AAD admin / user with `CREATE` rights.
