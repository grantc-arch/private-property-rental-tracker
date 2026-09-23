"""
PrivateProperty.co.za rental watcher — Stellenbosch
Same architecture as the Property24 bot: Playwright fetch -> BeautifulSoup parse
-> diff against seen.json -> Telegram alert for new listings.

IMPORTANT: PrivateProperty's HTML structure has NOT been verified live in this
build (their search pages weren't reachable via search/fetch when this was
written). Before running this for real:
  1. Open the search URL below in a browser.
  2. Right-click a listing card -> Inspect.
  3. Update the CSS selectors marked "# CONFIRM" to match what you see.
Everything else (dedup logic, Telegram alerting, GitHub Actions schedule)
should work unchanged once the selectors are correct.
"""

import asyncio
import json
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import requests

# --- Config ---------------------------------------------------------------

# Adjust suburb/price/bedroom filters as needed via PrivateProperty's own
# search UI, then copy the resulting URL here (sorted by newest if possible).
SEARCH_URL = "https://www.privateproperty.co.za/to-rent/western-cape/stellenbosch/9/8016"

SEEN_FILE = Path("seen_privateproperty.json")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# --- Fetch ------------------------------------------------------------------

async def fetch_html(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        await page.goto(url, wait_until="networkidle", timeout=30000)
        # PrivateProperty may lazy-load cards on scroll — nudge it.
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(1500)
        html = await page.content()
        await browser.close()
        return html


# --- Parse -------------------------------------------------------------------

def parse_listings(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    listings = []

    # CONFIRM: container for each listing card. Common PP patterns are
    # div[data-testid="listing-result"] or similar — check real markup.
    cards = soup.select('[data-testid*="listing"]')  # CONFIRM

    for card in cards:
        try:
            # CONFIRM each of these selectors against the real DOM
            link_el = card.select_one("a")
            title_el = card.select_one('[data-testid*="title"]') or card.select_one("h3")
            price_el = card.select_one('[data-testid*="price"]')
            beds_el = card.select_one('[data-testid*="bedroom"]')
            address_el = card.select_one('[data-testid*="address"]') or card.select_one("address")

            if not link_el or not link_el.get("href"):
                continue

            href = link_el["href"]
            if href.startswith("/"):
                href = "https://www.privateproperty.co.za" + href

            listing_id_match = re.search(r"(\d{5,})", href)
            listing_id = listing_id_match.group(1) if listing_id_match else href

            listings.append({
                "id": listing_id,
                "url": href,
                "title": title_el.get_text(strip=True) if title_el else "Untitled listing",
                "price": price_el.get_text(strip=True) if price_el else "Price on request",
                "beds": beds_el.get_text(strip=True) if beds_el else "Beds not listed",
                "address": address_el.get_text(strip=True) if address_el else "Stellenbosch",
            })
        except Exception as e:
            print(f"Skipped a card due to parse error: {e}")
            continue

    return listings


# --- Dedup / state ------------------------------------------------------------

def load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set[str]) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen)))


# --- Telegram ------------------------------------------------------------------

def send_telegram_alert(listing: dict) -> None:
    message = (
        f"🏠 New PrivateProperty listing in Stellenbosch\n\n"
        f"{listing['title']}\n"
        f"📍 {listing['address']}\n"
        f"💰 {listing['price']}\n"
        f"🛏️ {listing['beds']}\n\n"
        f"{listing['url']}"
    )
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "disable_web_page_preview": False},
        timeout=15,
    )
    if not resp.ok:
        print(f"Telegram send failed: {resp.status_code} {resp.text}")


# --- Main -----------------------------------------------------------------

async def main():
    html = await fetch_html(SEARCH_URL)
    listings = parse_listings(html)

    if not listings:
        print("No listings parsed — selectors likely need updating (see CONFIRM comments).")
        return

    seen = load_seen()
    new_listings = [l for l in listings if l["id"] not in seen]

    print(f"Parsed {len(listings)} listings, {len(new_listings)} new.")

    for listing in new_listings:
        send_telegram_alert(listing)
        seen.add(listing["id"])

    save_seen(seen)


if __name__ == "__main__":
    asyncio.run(main())
