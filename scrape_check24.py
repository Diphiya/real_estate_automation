"""
Cirrus Real Estate — Check24 Market Price Scraper (Robust Version)
Handles dynamic UI, fallback selectors, and resilient extraction.
"""

import argparse
import asyncio
import json
import re
import sys

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("playwright not installed. Run:")
    print("pip install playwright")
    print("playwright install chromium")
    sys.exit(1)

CHECK24_URL = "https://www.check24.de/baufinanzierung/immobilienbewertung/"


# ─────────────────────────────────────────────────────────────
# Helper: Find first working selector
# ─────────────────────────────────────────────────────────────
async def find_input(page, selectors, timeout=15000):
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout)
            if el:
                return el
        except PlaywrightTimeout:
            continue
    return None


# ─────────────────────────────────────────────────────────────
# Main Scraper
# ─────────────────────────────────────────────────────────────
async def get_market_price(address: str, sqm: float, build_year: int, headless=True):
    result = {
        "price_per_sqm": None,
        "total_value": None,
        "raw": ""
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, slow_mo=50)
        context = await browser.new_context(locale="de-DE")
        page = await context.new_page()

        try:
            print(f"Opening {CHECK24_URL}")
            await page.goto(CHECK24_URL, wait_until="domcontentloaded", timeout=60000)

            # Give JS time to render UI
            await page.wait_for_timeout(4000)

            # ── Cookies ─────────────────────────────────────
            try:
                await page.click("button:has-text('Alle akzeptieren')", timeout=4000)
                print("Cookie banner dismissed.")
                await page.wait_for_timeout(1000)
            except:
                pass

            # ── ADDRESS INPUT ───────────────────────────────
            print("Locating address input...")

            address_selectors = [
                'input[placeholder*="Adresse"]',
                'input[placeholder*="Straße"]',
                'input[name*="address"]',
                'input[id*="address"]',
                'input[type="text"]'
            ]

            addr_input = await find_input(page, address_selectors)

            if not addr_input:
                raise Exception("Address input not found.")

            print(f"Entering address: {address}")
            await addr_input.click()
            await addr_input.fill(address)
            await page.wait_for_timeout(2000)

            # Autocomplete selection
            try:
                await page.keyboard.press("ArrowDown")
                await page.keyboard.press("Enter")
            except:
                pass

            await page.wait_for_timeout(2000)

            # ── OBJECT TYPE ────────────────────────────────
            try:
                await page.click("text=Mehrfamilienhaus", timeout=4000)
            except:
                try:
                    await page.click("text=Wohnung", timeout=4000)
                except:
                    print("Object type not selected (continuing).")

            # ── AREA INPUT ─────────────────────────────────
            sqm_input = await find_input(page, [
                'input[placeholder*="m²"]',
                'input[name*="area"]',
                'input[name*="flaeche"]'
            ])

            if sqm_input:
                await sqm_input.fill(str(int(sqm)))
            else:
                print("Area input not found.")

            # ── YEAR INPUT ─────────────────────────────────
            year_input = await find_input(page, [
                'input[placeholder*="Baujahr"]',
                'input[name*="year"]'
            ])

            if year_input:
                await year_input.fill(str(build_year))
            else:
                print("Build year input not found.")

            # ── SUBMIT ─────────────────────────────────────
            try:
                await page.click("button:has-text('Bewerten')", timeout=5000)
            except:
                try:
                    await page.click("button:has-text('Berechnen')", timeout=5000)
                except:
                    print("Submit button not found.")

            await page.wait_for_timeout(5000)

            # ── EXTRACT RESULTS ────────────────────────────
            print("Extracting results...")

            content = await page.content()
            result["raw"] = content[:2000]

            # Strategy 1: direct selectors
            selectors = [
                '[data-testid*="price"]',
                '[class*="price"]',
                '[class*="value"]'
            ]

            for sel in selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        text = await el.inner_text()
                        nums = re.findall(r'[\d.,]+', text)
                        if nums:
                            val = float(nums[0].replace('.', '').replace(',', '.'))
                            if 500 < val < 15000:
                                result["price_per_sqm"] = val
                                result["total_value"] = round(val * sqm, 0)
                                break
                except:
                    continue

            # Strategy 2: full text scan (fallback)
            if not result["price_per_sqm"]:
                print("Fallback: scanning full page text...")
                full_text = await page.evaluate("() => document.body.innerText")

                matches = re.findall(r'(\d{1,4}[.,]\d{3})\s*€', full_text)
                values = [float(m.replace('.', '').replace(',', '.')) for m in matches]

                for v in sorted(values):
                    if 500 < v < 15000:
                        result["price_per_sqm"] = v
                        result["total_value"] = round(v * sqm, 0)
                        break

            # Debug screenshot
            await page.screenshot(path="check24_debug.png")
            print("Screenshot saved: check24_debug.png")

        except Exception as e:
            print(f"Scraping error: {e}")

        finally:
            await browser.close()

    return result


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", required=True)
    parser.add_argument("--sqm", type=float, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--no-headless", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(get_market_price(
        address=args.address,
        sqm=args.sqm,
        build_year=args.year,
        headless=not args.no_headless
    ))

    print("\nRESULT:")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()