# SkyCargo OCR — AWB extraction & engine comparison

Runs OCR on air waybill (AWB) PDFs with **two** engines, then uses **gpt-5.4**
as an impartial judge to decide which engine is more precise.

| Script | Engine | Output per `name.pdf` |
|---|---|---|
| `docintell_ocr.py` | Azure AI Document Intelligence (`prebuilt-layout`) | `output/name.json`, `output/name.md` |
| `agent_ocr.py` | Microsoft Foundry prompt agent (gpt-5.4 vision) | `output/name.agent.json`, `output/name.agent.md` |
| `compare_ocr.py` | local text diff (no Azure calls) | `output/name.compare.md`, `output/comparison-summary.json` |
| `judge_ocr.py` | gpt-5.4 as ground-truth adjudicator | `output/name.verdict.json`, `output/name.verdict.md`, `output/verdict-summary.json` |

## How it works

1. Drop one or more PDFs into the [input](input) folder.
2. Run `docintell_ocr.py` and `agent_ocr.py` to produce both transcriptions.
3. Run `compare_ocr.py` to see how *similar* they are (no ground truth).
4. Run `judge_ocr.py` to have gpt-5.4 read the original PDF and decide which
   engine is more *correct*, with per-field adjudication and a winner.

## Setup

```powershell
# from the skycargo-ocr folder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Configuration (`.env`)

The `.env` is already filled in for the provided resources:

```ini
# Document Intelligence (docintell_ocr.py)
DOCUMENTINTELLIGENCE_ENDPOINT=https://docintelligencmbc.cognitiveservices.azure.com/
DOCUMENTINTELLIGENCE_API_KEY=                 # leave blank to use Azure AD
DOCUMENTINTELLIGENCE_MODEL=prebuilt-layout

# Foundry agent + judge (agent_ocr.py, judge_ocr.py) — Azure AD only
FOUNDRY_PROJECT_ENDPOINT=https://mydevfoundry0603.services.ai.azure.com/api/projects/devproject
FOUNDRY_MODEL_DEPLOYMENT=gpt-5.4
FOUNDRY_AGENT_NAME=skycargo-ocr-agent
```

### Authentication

```powershell
az login
```

- **Document Intelligence** uses the API key if `DOCUMENTINTELLIGENCE_API_KEY`
  is set, otherwise falls back to Azure AD (`az login`). Your identity needs
  the **Cognitive Services User** role on `docintelligencmbc`.
- **Foundry agent & judge** use Azure AD only (no keys) — Azure CLI credential
  locally, Managed Identity in Azure. Your identity needs access to the
  Foundry project `devproject` on `mydevfoundry0603`.

## Run

```powershell
# 1. Document Intelligence OCR
python docintell_ocr.py

# 2. Foundry agent (gpt-5.4) OCR
python agent_ocr.py

# 3. Local similarity comparison (optional, no Azure calls)
python compare_ocr.py

# 4. gpt-5.4 judge — declares the more precise engine
python judge_ocr.py
```

### Run the judge agent

`judge_ocr.py` requires both `output/name.json` (Document Intelligence) and
`output/name.agent.json` (Foundry agent) to exist for the same PDF, so run
steps 1 and 2 first. Then:

```powershell
python judge_ocr.py
```

Example output:

```
Judging 1 document(s) with 'gpt-5.4' as ground-truth adjudicator.

  AWB-001-82825555: winner=agent (DI 72 vs agent 91) -> output\AWB-001-82825555.verdict.md

Done. 1 judged, 0 failed. Summary -> output\verdict-summary.json
```

For each document the judge writes:

- `output/name.verdict.json` — scores (accuracy, completeness, structure,
  hallucination), per-critical-field adjudication, and the winner.
- `output/name.verdict.md` — human-readable verdict.
- `output/verdict-summary.json` — roll-up across all judged documents.

## Model selection (Document Intelligence)

Set `DOCUMENTINTELLIGENCE_MODEL` in `.env`:

| Model | Use |
|---|---|
| `prebuilt-layout` (default) | Text + tables + structure — best for AWBs |
| `prebuilt-read` | Plain text / handwriting only, faster |

## Resources

- Document Intelligence: `docintelligencmbc` (rg `logicapp-rg`)
- Foundry: `mydevfoundry0603`, project `devproject`, model `gpt-5.4`
- Subscription: `7d1e8453-2920-4f6d-9a6e-bc7005c10a22`
