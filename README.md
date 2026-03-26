# Cirrus Exposé Automation — Ollama Version (Improved)

100% offline, local LLM pipeline. No API key, no cloud, data never leaves your machine.

---

## What's new vs the original

| Area | Original | Improved |
|---|---|---|
| LLM retry logic | Single call | 3 retries with progressively stricter prompts |
| Table extraction | Basic blocks | Word-position grouping for better row alignment |
| Missing cost fields | Left null | Auto-derived from config rates (brokerFee, ancillaryCosts, finCosts) |
| Deal scoring | Not present | Score 0–100, Yield check, Multiplier check → ACQUIRE / REVIEW / SKIP |
| Extras income | Hardcoded €50/58/350 | Extracted from PDF, configurable in config.json |
| OCR fallback | Not present | Tries pytesseract if PDF has no extractable text |
| Excel sheets | 4 sheets | 5 sheets + new **📊 Deal Score** summary sheet with color-coded recommendation |
| Excel formatting | Basic blue font | Styled headers, alternating rows, color-coded profit/loss cells |
| Google Drive auth | Breaks after 1hr | Token refresh — re-auth only needed once |
| Drive folder dedup | Creates duplicate folders | find_or_create avoids duplicates |
| HTML interface | Fixed demo data | Live Ollama call + 3-attempt retry, JSON download added |
| HTML UX | Dark minimal | Refined dark UI with DM Sans/Mono fonts, score meter, rec badge |

---

## Files

| File | Purpose |
|---|---|
| `cirrus_expose_automation_ollama.html` | Browser prototype — open directly, no install |
| `pipeline_ollama.py` | Full CLI pipeline orchestrator |
| `extract_expose_ollama.py` | PDF extraction → Ollama → validated JSON |
| `populate_excel.py` | Excel template with 5 sheets + deal score |
| `google_drive.py` | Google Drive upload (token refresh + dedup) |
| `config.json` | All thresholds and model settings |

---

## Quick start (browser prototype)

1. `ollama serve`
2. `ollama pull llama3.1`
3. Open `cirrus_expose_automation_ollama.html` in Chrome/Firefox
4. Click **Check** — it auto-discovers available models
5. Enter market price from Check24, upload PDF → **Run Pipeline**
6. Download Excel or JSON with the buttons at the bottom of the sidebar

The browser calls Ollama directly at `http://localhost:11434`.
PDF text extraction (PyMuPDF) requires the Python CLI for full accuracy.

---

## Install & run (Python CLI)

### 1. Install Ollama

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows: https://ollama.com/download
```

### 2. Pull a model

```bash
ollama pull llama3.1       # best all-round (~4.7GB)
ollama pull mistral        # fast, good JSON (~4.1GB)
ollama pull qwen2.5        # strong multilingual (~4.7GB)
```

### 3. Install Python dependencies

```bash
pip install ollama pymupdf openpyxl \
    google-auth google-auth-oauthlib google-auth-httplib2 \
    google-api-python-client requests

# Optional OCR (for scanned PDFs):
pip install pytesseract pillow
# + install Tesseract: https://tesseract-ocr.github.io/tessdoc/Installation.html
# with German pack: apt install tesseract-ocr-deu
```

### 4. Run the pipeline

```bash
# Start Ollama (leave running in a separate terminal)
ollama serve

# Basic run:
python pipeline_ollama.py expose.pdf --model llama3.1

# With Check24 market price (manually entered):
python pipeline_ollama.py expose.pdf --price-sqm 3200

# Fully offline (no Drive upload):
python pipeline_ollama.py expose.pdf --price-sqm 3200 --offline

# Different model:
python pipeline_ollama.py expose.pdf --model mistral --price-sqm 3000
```

### 5. Individual steps

```bash
# Extract only (saves extracted_data.json)
python extract_expose_ollama.py expose.pdf --model llama3.1

# Populate Excel (needs extracted_data.json)
python populate_excel.py extracted_data.json --price-sqm 3200

# Google Drive (one-time OAuth setup)
python google_drive.py --auth
python google_drive.py --address BernauOranienburgerStr6 --share you@example.com

# Dry run (see what would be uploaded)
python google_drive.py --dry-run --address TestProperty
```

---

## Deal Scoring

The pipeline automatically calculates a **Deal Score (0–100)** based on:

| Criteria | Points | Source |
|---|---|---|
| Gross yield ≥ target (default 4.5%) | +30 max | config.acquisitionCriteria.targetGrossYield |
| Rent multiplier ≤ max (default 22x) | +10 | config.acquisitionCriteria.maxMultiplier |
| Fully rented | +5 | extracted from PDF |
| Energy class below D | -5 | extracted from PDF |

**Score interpretation:**
- ≥ 70 → **ACQUIRE**
- 50–69 → **REVIEW**
- < 50 → **SKIP**

Adjust thresholds in `config.json` without touching any code.

---

## How extraction works

| Step | What happens |
|---|---|
| 1 | PyMuPDF extracts text from every page (layout-preserving) |
| 2 | Word-position table extraction improves Mieterliste accuracy |
| 3 | If very little text found → tries OCR via pytesseract |
| 4 | Combined text sent to Ollama with strict JSON-only system prompt |
| 5 | Up to 3 retries if response doesn't parse as valid JSON |
| 6 | Post-processing fills missing cost fields from config rates |
| 7 | Deal metrics computed (yield, multiplier, score) |
| 8 | JSON validated against required fields + confidence thresholds |

---

## Model recommendations

| Model | Size | German | JSON reliability | Notes |
|---|---|---|---|---|
| `llama3.1` | 8B | ★★★★ | ★★★★ | Best all-rounder |
| `mistral` | 7B | ★★★★ | ★★★★ | Fast, reliable JSON |
| `qwen2.5` | 7B | ★★★★ | ★★★★ | Strong multilingual |
| `gemma2` | 9B | ★★★☆ | ★★★★ | Good structured data |
| `phi3` | 3.8B | ★★★☆ | ★★★☆ | Fastest, lower accuracy |
| `llama3.1:70b` | 70B | ★★★★★ | ★★★★★ | Best quality, needs GPU |

---

## Adjusting acquisition criteria

Edit `config.json` — no code changes needed:

```json
{
  "acquisitionCriteria": {
    "targetGrossYield": 4.5,   ← minimum yield %
    "maxMultiplier": 22,        ← max rent multiplier
    "flagEnergyClassesBelowD": true
  },
  "costs": {
    "brokerFeeRate": 0.0714,    ← auto-derive broker fee if not in exposé
    "transferTaxRate": 0.06,    ← Brandenburg Grunderwerbsteuer
    "notaryRate": 0.02
  }
}
```

---

## Error handling

| Problem | What happens |
|---|---|
| Ollama not running | Clear error + tip to run `ollama serve` |
| Model not pulled | Warning + `ollama pull <model>` tip |
| LLM returns non-JSON | Retry up to 3x with stricter prompt |
| Field missing from PDF | Auto-derived from config, or `null` in JSON |
| PDF has no text (scanned) | OCR fallback via pytesseract (if installed) |
| Google token expired | Automatic refresh — no re-auth needed |
| Drive folder already exists | Reuses existing folder (no duplicates) |

---

## Output files

```
extracted_data.json               ← Ollama extraction + deal metrics
Cirrus_BusinessCase_YYYY-MM-DD.xlsx ← 5-sheet Excel (Deal Score, Stammdaten, Mieterliste, Verkauf, Business Case)
pipeline_result.json              ← Full pipeline run summary
extracted_photos/                 ← Images extracted from PDF
```

---

## Changelog vs original submission

| Fix | Detail |
|---|---|
| `populate_excel.py` | Now writes into **Case_Study__Aufteiler_.xlsx** at exact cell positions; preserves all formulas and named ranges (Kaufpreis → C45, WFL_Wohnen → C33, etc.) |
| `pipeline_ollama.py` | Google Photos step restored as step 5; passes `extracted_photos/` folder and album named `{address}_{date}` |
| `google_drive.py` | Token refresh so re-auth only needed once; `find_or_create_folder` prevents duplicates |
| `TechStack_Cirrus_Expose_Automation.docx` | 1-page tech stack summary ready to email to as@cirrus-real.de |
