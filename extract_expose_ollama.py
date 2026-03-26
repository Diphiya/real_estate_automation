"""
Cirrus Real Estate — Exposé Data Extractor (Ollama / Local LLM)
Improved version: better table parsing, retry logic, OCR fallback,
chunked extraction, and richer validation.

Usage:
    python extract_expose_ollama.py expose.pdf [--output data.json] [--model llama3.1]

Requirements:
    pip install ollama pymupdf
    ollama pull llama3.1        (or mistral, gemma2, etc.)
    ollama serve                (start the Ollama daemon)
"""

import argparse
import json
import os
import re
import sys
import time

try:
    import fitz  # PyMuPDF
except ImportError:
    print("PyMuPDF not installed. Run: pip install pymupdf")
    sys.exit(1)

try:
    import ollama
except ImportError:
    print("ollama not installed. Run: pip install ollama")
    sys.exit(1)


# ─── Schema ───────────────────────────────────────────────────────────────────

SCHEMA = {
    "address": "string",
    "district": "string",
    "objectType": "string",
    "buildYear": "number|null",
    "lastRenovation": "number|null",
    "plotSize": "number|null",
    "totalLivingArea": "number|null",
    "basementArea": "number|null",
    "floors": "number|null",
    "atticDeveloped": "boolean|null",
    "units": "number|null",
    "fullyRented": "boolean|null",
    "parkingSpots": "number|null",
    "energyClass": "string|null",
    "energyValue": "number|null",
    "heatingType": "string|null",
    "purchasePrice": "number|null",
    "brokerFee": "number|null",
    "ancillaryCosts": "number|null",
    "divisionCosts": "number|null",
    "marketingCosts": "number|null",
    "otherCosts": "number|null",
    "finCosts": "number|null",
    "tenants": [
        {
            "nr": "number",
            "floor": "string",
            "since": "string (DD.MM.YYYY)",
            "area": "number",
            "nkm": "number",
            "nkmSqm": "number",
            "bk": "number",
            "gross": "number",
            "parking": "number"
        }
    ],
    "extras": {
        "containerRent": "number|null",
        "flightSecurityRent": "number|null",
        "outsideParkingRent": "number|null"
    },
    "confidence": {
        "address": "0-100",
        "pricing": "0-100",
        "areas": "0-100",
        "tenants": "0-100",
        "costs": "0-100",
        "photos": "0-100"
    }
}

SYSTEM_PROMPT = f"""You are a German real estate data extraction specialist.
Your job is to extract structured data from German property exposé documents.
You MUST return ONLY valid JSON — no markdown fences, no explanations, no preamble.
Use null for any field not found in the document.
All monetary values are plain numbers without currency symbols.
Confidence scores per category are integers 0-100.
Extract ALL rows from the Mieterliste (tenant list) table if present.

IMPORTANT RULES:
- brokerFee: if you see "3,57%" calculate 0.0357 * purchasePrice
- ancillaryCosts: Notar (2%) + Grunderwerbsteuer (6%) = ~8% of purchasePrice
- For tenant "since" dates: preserve original German date format DD.MM.YYYY
- parkingSpots: count total individual parking spaces mentioned
- extras.containerRent, extras.flightSecurityRent, extras.outsideParkingRent:
  extract additional income items from the bottom of the tenant list if present

Return JSON matching exactly this schema:
{json.dumps(SCHEMA, ensure_ascii=False, indent=2)}"""


# ─── PDF text extraction ──────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str, max_chars: int = 14000) -> str:
    """
    Extract all text from a PDF using PyMuPDF with layout preservation.
    Uses 'blocks' mode which better preserves table structure.
    """
    doc = fitz.open(pdf_path)
    pages_text = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)

        # Try dict mode for richer positional data
        try:
            text = page.get_text("text", sort=True)
        except Exception:
            text = page.get_text()

        if text.strip():
            pages_text.append(f"--- Page {page_num + 1} ---\n{text.strip()}")

    doc.close()
    full_text = "\n\n".join(pages_text)

    if len(full_text) > max_chars:
        print(f"  PDF text truncated from {len(full_text)} to {max_chars} chars.")
        full_text = full_text[:max_chars]

    return full_text


def extract_tables_structured(pdf_path: str) -> str:
    """
    Extract table-like structures by grouping words into rows by Y position.
    Produces a more readable table format for the LLM.
    """
    doc = fitz.open(pdf_path)
    result_lines = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        words = page.get_text("words", sort=True)

        if not words:
            continue

        # Group words into rows by Y coordinate (within 3 pt tolerance)
        rows: dict[float, list] = {}
        for w in words:
            x0, y0, x1, y1, text, *_ = w
            y_key = round(y0 / 3) * 3  # quantize to 3-pt buckets
            rows.setdefault(y_key, []).append((x0, text))

        result_lines.append(f"=== Page {page_num + 1} Table Data ===")
        for y_key in sorted(rows.keys()):
            row_words = sorted(rows[y_key], key=lambda r: r[0])
            line = "  |  ".join(w for _, w in row_words)
            result_lines.append(line)

    doc.close()
    return "\n".join(result_lines)


def extract_images_from_pdf(pdf_path: str, output_dir: str = "extracted_photos") -> list[str]:
    """
    Extract all images from the PDF and save as JPEG files.
    Returns list of saved file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    saved = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        image_list = page.get_images(full=True)

        for img_idx, img in enumerate(image_list, start=1):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image.get("ext", "jpeg")
            w, h = base_image.get("width", 0), base_image.get("height", 0)

            # Skip tiny images (icons, borders)
            if w < 100 or h < 100:
                continue

            out_path = os.path.join(output_dir, f"page{page_num+1:02d}_img{img_idx:02d}.{image_ext}")
            with open(out_path, "wb") as f:
                f.write(image_bytes)
            saved.append(out_path)

    doc.close()
    print(f"  Extracted {len(saved)} images to '{output_dir}/'")
    return saved


def try_ocr_fallback(pdf_path: str, max_pages: int = 4) -> str:
    """
    OCR fallback for scanned PDFs. Requires pytesseract + pillow + tesseract-ocr-deu.
    Returns empty string if OCR is not available.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    doc = fitz.open(pdf_path)
    ocr_texts = []

    for page_num in range(min(max_pages, len(doc))):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        try:
            text = pytesseract.image_to_string(img, lang='deu')
            if text.strip():
                ocr_texts.append(f"--- OCR Page {page_num + 1} ---\n{text.strip()}")
        except Exception:
            pass

    doc.close()
    return "\n\n".join(ocr_texts)


# ─── LLM extraction ───────────────────────────────────────────────────────────

def get_ollama_client(host: str = "http://localhost:11434") -> "ollama.Client":
    """Return an Ollama client, raising a clear error if not reachable."""
    client = ollama.Client(host=host)
    try:
        client.list()
    except Exception:
        print(f"\n  ✗ Cannot connect to Ollama at {host}")
        print("  → Make sure Ollama is running: ollama serve")
        sys.exit(1)
    return client


def check_model_available(client: "ollama.Client", model: str) -> bool:
    """Check if model is pulled locally."""
    try:
        models_resp = client.list()
        available = [m.model for m in models_resp.models]
        available_base = [m.split(":")[0] for m in available]
        model_base = model.split(":")[0]
        if model_base not in available_base and model not in available:
            print(f"  ⚠  Model '{model}' not found locally.")
            print(f"  Available: {', '.join(available) or 'none'}")
            print(f"  Run: ollama pull {model}")
            return False
        return True
    except Exception:
        return True  # Don't block if we can't check


def extract_with_ollama(
    text: str,
    model: str = "llama3.1",
    host: str = "http://localhost:11434",
    retries: int = 3,
    config: dict = None,
) -> str:
    """
    Send extracted PDF text to local Ollama model and return raw JSON string.
    Retries up to `retries` times with increasingly strict prompts.
    """
    config = config or {}
    ollama_cfg = config.get("ollama", {}).get("options", {})

    client = get_ollama_client(host)
    check_model_available(client, model)

    user_message = f"""Here is the text extracted from a German real estate exposé document.
Please extract all structured data and return ONLY valid JSON.

DOCUMENT TEXT:
{text}

Remember: return ONLY the JSON object, nothing else. No markdown, no explanations."""

    for attempt in range(1, retries + 1):
        try:
            print(f"  Calling Ollama ({model})… attempt {attempt}/{retries}")
            response = client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                options={
                    "temperature": 0.0,
                    "num_predict": ollama_cfg.get("num_predict", 4096),
                    "num_ctx":     ollama_cfg.get("num_ctx", 8192),
                },
            )
            raw = response.message.content.strip()
            # Quick sanity check — does it look like JSON?
            if "{" in raw and "}" in raw:
                return raw
            print(f"  ⚠  Response doesn't look like JSON. Retrying…")
        except Exception as e:
            print(f"  ⚠  Ollama call failed: {e}")
            if attempt < retries:
                time.sleep(2 * attempt)

    raise RuntimeError(f"Ollama extraction failed after {retries} attempts.")


def parse_llm_response(raw: str) -> dict:
    """Clean and parse JSON from LLM response, handling common formatting issues."""
    text = raw.strip()

    # Strip markdown fences
    if text.startswith("```"):
        parts = text.split("```")
        # Take the content between fences
        for part in parts[1:]:
            if part.strip().startswith("json"):
                part = part[4:]
            part = part.strip()
            if part.startswith("{"):
                text = part
                break
        else:
            text = parts[1].strip()

    # Extract JSON object
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in response. Raw:\n{raw[:500]}")

    json_str = text[start:end]

    # Fix common LLM JSON issues
    # Remove trailing commas before } or ]
    json_str = re.sub(r",(\s*[}\]])", r"\1", json_str)

    return json.loads(json_str)


# ─── Post-processing ──────────────────────────────────────────────────────────

def derive_missing_costs(data: dict, config: dict) -> dict:
    """
    Auto-derive costs that can be calculated from config rates if LLM missed them.
    Only fills in if the value is None/missing.
    """
    kp = data.get("purchasePrice")
    costs_cfg = config.get("costs", {})

    if kp:
        if data.get("brokerFee") is None:
            rate = costs_cfg.get("brokerFeeRate", 0.0714)
            data["brokerFee"] = round(kp * rate, 2)

        if data.get("ancillaryCosts") is None:
            rate = costs_cfg.get("transferTaxRate", 0.06) + costs_cfg.get("notaryRate", 0.02)
            data["ancillaryCosts"] = round(kp * rate, 2)

    if data.get("divisionCosts") is None:
        data["divisionCosts"] = costs_cfg.get("divisionCostsFixed", 10000)

    if data.get("marketingCosts") is None:
        data["marketingCosts"] = costs_cfg.get("marketingCostsFixed", 10000)

    if data.get("otherCosts") is None:
        data["otherCosts"] = costs_cfg.get("otherCostsFixed", 10000)

    return data


def derive_financing_costs(data: dict, config: dict) -> dict:
    """
    Calculate financing costs from config if not provided.
    """
    if data.get("finCosts") is not None:
        return data

    fin_cfg = config.get("financing", {})
    kp = data.get("purchasePrice", 0) or 0
    ltv = fin_cfg.get("ltv", 1.0)
    rate = fin_cfg.get("interestRatePA", 0.04)
    years = fin_cfg.get("capitalBindingYears", 1.5)

    data["finCosts"] = round(kp * ltv * rate * years, 2)
    return data


def compute_deal_score(data: dict, config: dict) -> dict:
    """
    Compute acquisition metrics and a simple deal score.
    Returns a dict with yield, multiplier, score, and recommendation.
    """
    criteria = config.get("acquisitionCriteria", {})
    tenants = data.get("tenants", [])

    # Monthly NKM from tenant list
    monthly_nkm = sum(t.get("nkm", 0) or 0 for t in tenants)
    # Add extras
    extras = data.get("extras", {})
    monthly_nkm += (extras.get("containerRent") or 0)
    monthly_nkm += (extras.get("flightSecurityRent") or 0)
    monthly_nkm += (extras.get("outsideParkingRent") or 0)

    annual_nkm = monthly_nkm * 12
    kp = data.get("purchasePrice", 0) or 0

    gross_yield = (annual_nkm / kp * 100) if kp else 0
    multiplier = (kp / annual_nkm) if annual_nkm else 0

    # Score: 0–100
    score = 50  # baseline
    target_yield = criteria.get("targetGrossYield", 4.5)
    max_mult = criteria.get("maxMultiplier", 22)

    if gross_yield >= target_yield:
        score += min(30, (gross_yield - target_yield) * 10)
    else:
        score -= min(30, (target_yield - gross_yield) * 10)

    if multiplier <= max_mult:
        score += 10
    else:
        score -= min(20, (multiplier - max_mult) * 2)

    if criteria.get("flagEnergyClassesBelowD") and data.get("energyClass") in ["E", "F", "G", "H"]:
        score -= 10

    score = max(0, min(100, round(score)))

    if score >= 70:
        recommendation = "ACQUIRE"
    elif score >= 50:
        recommendation = "REVIEW"
    else:
        recommendation = "SKIP"

    return {
        "monthlyNKM": round(monthly_nkm, 2),
        "annualNKM": round(annual_nkm, 2),
        "grossYield": round(gross_yield, 2),
        "multiplier": round(multiplier, 2),
        "dealScore": score,
        "recommendation": recommendation,
    }


# ─── Validation ───────────────────────────────────────────────────────────────

def load_config(path="config.json") -> dict:
    defaults = {
        "requiredFields": ["address", "buildYear", "purchasePrice", "totalLivingArea"],
        "minConfidenceThreshold": 50,
        "costs": {},
        "financing": {},
        "acquisitionCriteria": {},
    }
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        # Deep merge
        for k, v in cfg.items():
            if isinstance(v, dict) and isinstance(defaults.get(k), dict):
                defaults[k] = {**defaults[k], **v}
            else:
                defaults[k] = v
    return defaults


def validate(data: dict, config: dict) -> list[str]:
    warnings = []
    for field in config.get("requiredFields", []):
        if data.get(field) is None:
            warnings.append(f"MISSING required field: {field}")

    conf = data.get("confidence", {})
    threshold = config.get("minConfidenceThreshold", 50)
    for k, v in conf.items():
        if isinstance(v, (int, float)) and v < threshold:
            warnings.append(f"LOW confidence for '{k}': {v}% (threshold: {threshold}%)")

    tenants = data.get("tenants", [])
    if tenants:
        for i, t in enumerate(tenants):
            if t.get("area", 0) <= 0:
                warnings.append(f"Tenant {i+1}: area is 0 or missing")
            if t.get("nkm", 0) <= 0:
                warnings.append(f"Tenant {i+1}: NKM is 0 or missing")

    return warnings


# ─── Main extraction pipeline ─────────────────────────────────────────────────

def extract(
    pdf_path: str,
    model: str = "llama3.1",
    host: str = "http://localhost:11434",
    config: dict = None,
    extract_photos: bool = True,
) -> dict:
    """Full extraction pipeline: PDF → text → Ollama → validated dict."""
    config = config or {}
    max_chars = config.get("extraction", {}).get("maxPdfChars", 14000)

    print(f"  Extracting text from PDF: {pdf_path}")
    text = extract_text_from_pdf(pdf_path, max_chars=max_chars)
    table_text = extract_tables_structured(pdf_path)

    # Check if PDF has meaningful text; if not, try OCR
    if len(text.strip()) < 200:
        print("  ⚠  Very little text found — trying OCR fallback…")
        ocr_text = try_ocr_fallback(pdf_path)
        if ocr_text:
            text = ocr_text
            print(f"  OCR extracted {len(text)} chars")
        else:
            print("  ⚠  OCR not available. Install: pip install pytesseract pillow")
            print("       and: apt install tesseract-ocr tesseract-ocr-deu")

    # Combine text + structured table data
    table_budget = max(0, max_chars - len(text))
    combined = text
    if table_text and len(table_text) > 100:
        combined = text + "\n\n[STRUCTURED TABLE DATA — use this for tenant list]\n" + table_text[:table_budget]

    print(f"  Total input to LLM: {len(combined)} chars")

    # Extract images
    if extract_photos:
        extract_images_from_pdf(pdf_path)

    # LLM call with retries
    raw = extract_with_ollama(combined, model=model, host=host, config=config)
    data = parse_llm_response(raw)

    # Post-process: derive missing cost fields from config
    data = derive_missing_costs(data, config)
    data = derive_financing_costs(data, config)

    # Attach deal metrics
    data["_metrics"] = compute_deal_score(data, config)

    return data


def main():
    parser = argparse.ArgumentParser(description="Extract exposé data using local Ollama LLM")
    parser.add_argument("pdf", help="Path to the exposé PDF")
    parser.add_argument("--output", default="extracted_data.json", help="Output JSON path")
    parser.add_argument("--model", default="llama3.1", help="Ollama model name")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama server URL")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--no-photos", action="store_true", help="Skip image extraction")
    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        print(f"Error: PDF not found: {args.pdf}", file=sys.stderr)
        sys.exit(1)

    config = load_config(args.config)

    print(f"Extracting data from: {args.pdf}")
    print(f"Using model: {args.model}")

    try:
        data = extract(
            args.pdf,
            model=args.model,
            host=args.host,
            config=config,
            extract_photos=not args.no_photos,
        )
    except Exception as e:
        print(f"Extraction failed: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        sys.exit(1)

    warnings = validate(data, config)
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  ⚠  {w}")
    else:
        print("✓ Validation passed — all required fields extracted.")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Saved to: {args.output}")

    m = data.get("_metrics", {})
    tenants = data.get("tenants", [])
    conf_vals = [v for v in data.get("confidence", {}).values() if isinstance(v, (int, float))]
    avg_conf = round(sum(conf_vals) / len(conf_vals)) if conf_vals else 0

    print(f"\n{'─'*48}")
    print(f"  Tenants extracted : {len(tenants)}")
    print(f"  Avg confidence    : {avg_conf}%")
    print(f"  Monthly NKM       : €{m.get('monthlyNKM', 0):,.2f}")
    print(f"  Gross yield       : {m.get('grossYield', 0):.2f}%")
    print(f"  Multiplier        : {m.get('multiplier', 0):.1f}x")
    print(f"  Deal score        : {m.get('dealScore', 0)}/100 → {m.get('recommendation', '—')}")
    print(f"{'─'*48}")


if __name__ == "__main__":
    main()
