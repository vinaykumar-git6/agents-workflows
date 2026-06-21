# SkyCargo Infrastructure

Infrastructure-as-Code (Bicep) for the SkyCargo AWB platform.

## Structure

```
infrastructure/
  logic-apps-consumption/  # Logic Apps Consumption (SharePoint -> Blob ingest)
```

Each component folder contains:
- `main.bicep`        — the deployable template
- `main.bicepparam`   — environment parameter values
- `README.md`         — component-specific notes

## Conventions

- `targetScope = 'resourceGroup'` unless noted otherwise.
- Keyless / managed-identity access only (no shared keys, no secrets in params).
- Built-in role assignments are created in the template that owns the workload identity.
- Tags applied to every resource via a shared `tags` object.

## Deploy

```powershell
az deployment group create `
  --resource-group <rg-name> `
  --template-file logic-apps-consumption/main.bicep `
  --parameters logic-apps-consumption/main.bicepparam
```
