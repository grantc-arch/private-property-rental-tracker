"""
PrivateProperty.co.za rental watcher — Stellenbosch
Same architecture as the Property24 bot: Playwright fetch -> BeautifulSoup parse
-> diff against seen.json -> Telegram alert for new listings.

Selectors confirmed against live markup (Sept 2026):
  card    -> a.listing-result  (href, title attr both usable)
  title   -> .listing-result-title
  address -> .listing-result-address
  id      -> reference number in the href, e.g. .../RR4775153
  price   -> .listing-result-price doesn't reliably populate in a headless
             run, so price is extracted via regex over the card's raw text
             instead (looks for an "R 12 345" style pattern). Confirmed
             working against live listings.

If PrivateProperty changes their markup later, re-inspect a live listing card
(right-click -> Inspect) and update the selectors below.
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

# Stellenbosch Central, sorted newest first (same pattern as the Property24 bot).
SEARCH_URL = (
    "https://www.privateproperty.co.za/to-rent/western-cape/boland/stellenbosch/"
    "stellenbosch-central/412?sorttype=Date&sortorder=Descending"
)

# Filters applied in code (not via URL params, which aren't confirmed to work
# reliably on PrivateProperty). A listing must pass ALL of these to alert.
MAX_PRICE = 12000
# Matched against the listing's title text, case-insensitive. Covers "1
# Bedroom", "Bachelor" and "Studio" flats — PrivateProperty tends to label
# studios either way.
ALLOWED_TYPE_KEYWORDS = ["1 bedroom", "bachelor", "studio"]

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
        # PrivateProperty lazy-renders some card content on scroll.
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(1500)
        html = await page.content()
        await browser.close()
        return html


# --- Parse -------------------------------------------------------------------

def parse_listings(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    listings = []

    # Each listing is an <a class="listing-result" title="..." href="...">
    cards = soup.select("a.listing-result")

    for card in cards:
        try:
            href = card.get("href", "")
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.privateproperty.co.za" + href

            # Reference number in the URL, e.g. .../RR4775153
            listing_id_match = re.search(r"(RR\d+)", href)
            listing_id = listing_id_match.group(1) if listing_id_match else href

            price_el = card.select_one(".listing-result-price")
            price_text = price_el.get_text(strip=True) if price_el else ""

            # Fallback: scan the whole card's text for an "R 12 345" style
            # pattern, in case the specific price class isn't populated
            # (e.g. lazy-rendered content not fully captured in this run).
            if not price_text:
                card_text = card.get_text(" ", strip=True)
                price_match = re.search(r"R\s?[\d\s,]{3,}", card_text)
                price_text = price_match.group(0).strip() if price_match else "Price on request"

            title_el = card.select_one(".listing-result-title")
            address_el = card.select_one(".listing-result-address")

            # Bedroom count isn't in a dedicated class in this markup — it's
            # in the feature icons block. Fall back to the title attr, which
            # usually includes it (e.g. "2 Bedroom Apartment").
            title_attr = card.get("title", "")

            listings.append({
                "id": listing_id,
                "url": href,
                "title": title_el.get_text(strip=True) if title_el else (title_attr or "Untitled listing"),
                "price": price_text,
                "beds": title_attr or "Beds not listed",
                "address": address_el.get_text(strip=True) if address_el else "Stellenbosch",
            })
        except Exception as e:
            print(f"Skipped a card due to parse error: {e}")
            continue

    return listings


# --- Filtering ---------------------------------------------------------------

def parse_price_to_int(price_text: str) -> int | None:
    """'R 11 500 per month' -> 11500. Returns None if unparseable."""
    digits = re.sub(r"[^\d]", "", price_text)
    return int(digits) if digits else None


def matches_type(listing: dict) -> bool:
    type_text = f"{listing['title']} {listing['beds']}".lower()
    return any(keyword in type_text for keyword in ALLOWED_TYPE_KEYWORDS)


def matches_filters(listing: dict) -> bool:
    price = parse_price_to_int(listing["price"])
    if price is None or price > MAX_PRICE:
        return False
    return matches_type(listing)


def compute_median(prices: list[int]) -> int | None:
    if not prices:
        return None
    ordered = sorted(prices)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def render_price_scale(price: int, median: int, scale_max: int = 20000, width: int = 26) -> str:
    """R0 ───────────●─▲────────── R20k
    ● = this listing   ▲ = median
    Both markers clamp into the bar if the price exceeds scale_max."""
    def position(value: int) -> int:
        clamped = max(0, min(value, scale_max))
        return round((clamped / scale_max) * (width - 1))

    price_pos = position(price)
    median_pos = position(median)

    bar = ["─"] * width
    # Median first so the listing marker wins if they land on the same spot.
    bar[median_pos] = "▲"
    bar[price_pos] = "●"

    scale_line = f"R0 {''.join(bar)} R{scale_max // 1000}k"
    return scale_line


# --- Dedup / state ------------------------------------------------------------

def load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set[str]) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen)))


# --- Telegram ------------------------------------------------------------------

def send_telegram_alert(listing: dict, median: int | None) -> None:
    price = parse_price_to_int(listing["price"])

    scale_block = ""
    if median is not None and price is not None:
        scale_line = render_price_scale(price, median)
        scale_block = (
            f"\n`{scale_line}`\n"
            f"● this listing (R{price:,})   ▲ median (R{median:,})\n"
        )

    message = (
        f"🏠 New PrivateProperty listing in Stellenbosch\n\n"
        f"{listing['title']}\n"
        f"📍 {listing['address']}\n"
        f"💰 {listing['price']}\n"
        f"🛏️ {listing['beds']}\n"
        f"{scale_block}\n"
        f"{listing['url']}"
    )
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": False,
            "parse_mode": "Markdown",
        },
        timeout=15,
    )
    if not resp.ok:
        print(f"Telegram send failed: {resp.status_code} {resp.text}")


# --- Main -----------------------------------------------------------------

async def main():
    html = await fetch_html(SEARCH_URL)
    listings = parse_listings(html)

    if not listings:
        print("No listings parsed — PrivateProperty may have changed their markup, or the page didn't fully load.")
        return

    filtered = [l for l in listings if matches_filters(l)]
    print(f"Parsed {len(listings)} listings, {len(filtered)} match filters (≤R{MAX_PRICE}, 1-bed/studio/bachelor).")

    # Median across ALL 1-bed/studio/bachelor listings this run (not just the
    # ones under MAX_PRICE), so it reflects the real market, not a pre-filtered
    # slice — the alert is comparing "this listing" against "the market", not
    # against other cheap listings.
    same_type_prices = [
        p for l in listings
        if matches_type(l) and (p := parse_price_to_int(l["price"])) is not None
    ]
    median = compute_median(same_type_prices)
    if median is not None:
        print(f"Median 1-bed/studio/bachelor price this run: R{median:,} (n={len(same_type_prices)})")

    seen = load_seen()
    new_listings = [l for l in filtered if l["id"] not in seen]

    print(f"{len(new_listings)} new.")

    for listing in new_listings:
        send_telegram_alert(listing, median)
        seen.add(listing["id"])

    save_seen(seen)


if __name__ == "__main__":
    asyncio.run(main())
