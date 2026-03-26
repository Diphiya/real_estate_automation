"""
Cirrus Real Estate — Ollama Pipeline Orchestrator (UPDATED)
PDF → Extract → Check24 (optional) → Excel → Google Drive
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import date

# ── Imports ───────────────────────────────────────────
try:
    from extract_expose_ollama import extract, load_config, validate
except ImportError:
    print("Error: extract_expose_ollama.py not found."); sys.exit(1)

try:
    from populate_excel import populate
except ImportError:
    print("Error: populate_excel.py not found."); sys.exit(1)


# ── Logger ───────────────────────────────────────────
class Log:
    def __init__(self):
        self.steps = []
        self._t0 = time.time()

    def ok(self, step, detail=""):
        self.steps.append({"step": step, "status": "ok", "detail": detail})
        print(f"  ✓ {step}" + (f": {detail}" if detail else ""))

    def fail(self, step, detail=""):
        self.steps.append({"step": step, "status": "fail", "detail": detail})
        print(f"  ✗ {step}" + (f": {detail}" if detail else ""), file=sys.stderr)

    def skip(self, step, reason=""):
        self.steps.append({"step": step, "status": "skip", "detail": reason})
        print(f"  – {step}" + (f" (skipped: {reason})" if reason else ""))

    def summary(self):
        ok = sum(1 for s in self.steps if s["status"] == "ok")
        return {
            "date": date.today().isoformat(),
            "elapsed_s": round(time.time() - self._t0, 1),
            "steps_ok": ok,
            "steps_total": len(self.steps),
            "steps": self.steps
        }


# ── Helpers ───────────────────────────────────────────
def slug(address: str) -> str:
    s = re.sub(r"[^\w\s]", "", address or "Property")
    return re.sub(r"\s+", "_", s.strip())[:60]


def avg_conf(data):
    vals = [v for v in data.get("confidence", {}).values() if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals)) if vals else 0


def calculate_estimated_price(data, price_sqm):
    area = data.get("totalLivingArea") or 0
    try:
        return round(area * price_sqm, 2)
    except:
        return 0


# ── Steps ─────────────────────────────────────────────

def step_extract(pdf, model, host, config, log):
    print("\n[1/4] Extracting data from PDF…")
    try:
        data = extract(pdf, model=model, host=host, config=config)
        warns = validate(data, config)
        for w in warns:
            print(f"       ⚠  {w}")

        log.ok("PDF Extraction",
               f"{len(data.get('tenants',[]))} tenants · conf {avg_conf(data)}%")
        return data

    except Exception as e:
        log.fail("PDF Extraction", str(e))
        traceback.print_exc()
        return None


def step_check24(data, log, manual_price):
    print("\n[2/4] Getting market price (Check24)…")

    # Manual override (preferred like video)
    if manual_price and manual_price > 0:
        log.ok("Market Price", f"{manual_price} €/m² (manual)")
        return manual_price, "manual"

    try:
        from scrape_check24 import get_market_price
    except ImportError:
        log.skip("Check24", "module missing → fallback")
        return 3000, "fallback"

    import asyncio

    address = data.get("address")
    sqm = data.get("totalLivingArea")
    year = data.get("buildYear")

    if not address or not sqm:
        log.skip("Check24", "missing data → fallback")
        return 3000, "fallback"

    try:
        result = asyncio.run(get_market_price(address, sqm, year, headless=True))
        price_sqm = result.get("price_per_sqm")

        if price_sqm:
            log.ok("Check24", f"{price_sqm} €/m²")
            return price_sqm, "check24"

    except Exception as e:
        log.fail("Check24", str(e))

    # Final fallback
    fallback_price = 3000
    log.ok("Fallback Price", f"{fallback_price} €/m²")
    return fallback_price, "fallback"


def step_excel(data, price_sqm, price_source, config, template, log):
    print("\n[3/4] Populating Excel template…")
    try:
        out = f"Cirrus_BusinessCase_{date.today().isoformat()}.xlsx"

        data["estimated_price"] = calculate_estimated_price(data, price_sqm)
        data["price_per_sqm"] = price_sqm
        data["price_source"] = price_source

        result = populate(
            data,
            price_sqm,
            config,
            template_path=template,
            output_path=out,
            price_source=price_source
        )

        log.ok("Excel Population",
               f"{out} | €{data['estimated_price']:,}")
        return out

    except Exception as e:
        log.fail("Excel Population", str(e))
        traceback.print_exc()
        return None


def step_drive(address_slug, files, image_folder, log):
    print("\n[4/4] Uploading to Google Drive…")
    try:
        from google_drive import upload_all

        drive_result = upload_all(
            address=address_slug,
            files=files,
            image_folder=image_folder
        )

        log.ok("Google Drive", "Files + images uploaded")

        folder_url = drive_result.get("folder_url") or drive_result.get("projectFolder")
        if folder_url:
            print(f"\n📁 Google Drive Folder: {folder_url}\n")

        return drive_result

    except ImportError:
        log.skip("Google Drive", "module missing")
        return None

    except FileNotFoundError:
        log.fail("Google Drive", "credentials.json missing")
        return None

    except Exception as e:
        log.fail("Google Drive", str(e))
        return None


# ── Main ─────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Cirrus Exposé Automation — Ollama Pipeline")

    p.add_argument("pdf")
    p.add_argument("--model", default="llama3.1")
    p.add_argument("--host", default="http://localhost:11434")
    p.add_argument("--config", default="config.json")
    p.add_argument("--template", default="Case_Study__Aufteiler_.xlsx")
    p.add_argument("--price-sqm", type=float, default=0)
    p.add_argument("--offline", action="store_true")
    p.add_argument("--output-json", default="extracted_data.json")

    args = p.parse_args()

    if not os.path.exists(args.pdf):
        print(f"Error: PDF not found: {args.pdf}")
        sys.exit(1)

    print("\n" + "═"*56)
    print("  Cirrus Exposé Automation — Ollama Pipeline")
    print(f"  PDF   : {args.pdf}")
    print(f"  Model : {args.model}")
    print("═"*56)

    config = load_config(args.config)
    config.setdefault("ollama", {})["model"] = args.model

    log = Log()
    results = {"pdf": args.pdf, "model": args.model}

    # 1. Extract
    data = step_extract(args.pdf, args.model, args.host, config, log)
    if not data:
        sys.exit(1)

    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    results["json"] = args.output_json

    # 2. Price
    price_sqm, price_source = step_check24(data, log, args.price_sqm)

    # 3. Excel
    excel_path = step_excel(data, price_sqm, price_source, config, args.template, log)
    if excel_path:
        results["excel"] = excel_path

    # 4. Drive
    if not args.offline:
        files = [f for f in [args.pdf, args.output_json, excel_path] if f and os.path.exists(f)]
        addr_slug = slug(data.get("address") or "Property")

        drive_result = step_drive(
            addr_slug,
            files,
            config.get("extraction", {}).get("photoOutputDir", "extracted_photos"),
            log
        )

        if drive_result:
            results["drive"] = drive_result
    else:
        log.skip("Google Drive", "--offline")

    # Summary
    summary = log.summary()
    results["pipeline"] = summary

    with open("pipeline_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "═"*56)
    print(f"Pipeline complete in {summary['elapsed_s']}s")
    print(f"Steps OK: {summary['steps_ok']}/{summary['steps_total']}")
    print("═"*56 + "\n")


if __name__ == "__main__":
    main()