"""
Daily price logger for the "Was that Black Friday deal real?" project.

Reads products.csv, fetches the current price for each product, and appends
one row per product to data/prices.csv. Run once a day (GitHub Actions does
this for you). One pass a day, a few seconds between requests, honest
User-Agent. If a site blocks you, drop it rather than working around it.

Usage:
    python log_prices.py            # normal run
    python log_prices.py --debug    # also prints the raw JSON structure of
                                    # the first product, to fix the parser
"""
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ---- Settings -------------------------------------------------------------
PRODUCTS_FILE = Path("products.csv")
OUTPUT_FILE = Path("data/prices.csv")
DELAY_SECONDS = 4  # pause between requests, keep it polite

# CHANGE THIS: put your own contact so the site owner can reach you.
USER_AGENT = "BlackFridayPriceStudy/1.0 (student research project; contact: your-email@example.com)"

# Takealot's website loads product data from this JSON endpoint. It is not a
# documented public API, so the version number may change over time.
TAKEALOT_API = "https://api.takealot.com/rest/v-1-14-0/product-details/{plid}?platform=desktop"

SAST = timezone(timedelta(hours=2))
FIELDS = ["date", "timestamp", "retailer", "product_id", "name",
          "category", "price", "was_price", "in_stock", "status"]


# ---- Takealot -------------------------------------------------------------
def get_path(data, *path):
    """Safely walk nested dicts/lists; returns None if any step is missing."""
    for key in path:
        try:
            data = data[key]
        except (KeyError, IndexError, TypeError):
            return None
    return data


def to_number(value):
    if value is None:
        return None
    try:
        return float(str(value).replace("R", "").replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def parse_takealot(data):
    """Return (name, price, was_price, in_stock) from the API JSON.

    The exact JSON layout is the fragile part. Several likely locations are
    tried in order. Run with --debug and adjust here if these come back empty.
    """
    name = (get_path(data, "title")
            or get_path(data, "core", "title")
            or get_path(data, "event_data", "documents", "product", "title"))

    prices = get_path(data, "buybox", "prices")
    price = to_number(get_path(data, "buybox", "listing_price"))
    was = None
    if isinstance(prices, list) and prices:
        nums = [n for n in (to_number(p) for p in prices) if n is not None]
        if nums:
            if price is None:
                price = min(nums)
            if max(nums) > price:
                was = max(nums)  # crossed-out "was" price
    if price is None:
        price = to_number(get_path(data, "event_data", "documents", "product", "purchase_price"))

    stock = (get_path(data, "buybox", "is_add_to_cart_available")
             if get_path(data, "buybox") is not None else None)
    return name, price, was, stock


def fetch_takealot(url, debug=False):
    match = re.search(r"PLID(\d+)", url, re.IGNORECASE)
    if not match:
        return {"status": "bad_url"}
    plid = match.group(1)
    resp = requests.get(TAKEALOT_API.format(plid=plid),
                        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                        timeout=30)
    if resp.status_code != 200:
        return {"product_id": plid, "status": f"http_{resp.status_code}"}
    data = resp.json()
    if debug:
        print("Top-level keys:", list(data.keys()))
        print(json.dumps(data, indent=2)[:3000])
    name, price, was, stock = parse_takealot(data)
    return {"product_id": plid, "name": name, "price": price, "was_price": was,
            "in_stock": stock, "status": "ok" if price is not None else "parse_error"}


FETCHERS = {"takealot": fetch_takealot}


# ---- Main -----------------------------------------------------------------
def main():
    debug = "--debug" in sys.argv
    with PRODUCTS_FILE.open(newline="", encoding="utf-8") as f:
        products = [r for r in csv.DictReader(f) if r.get("url", "").strip()]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not OUTPUT_FILE.exists()
    now = datetime.now(SAST)
    ok = 0

    with OUTPUT_FILE.open("a", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for i, p in enumerate(products):
            retailer = p["retailer"].strip().lower()
            fetch = FETCHERS.get(retailer)
            row = {"date": now.date().isoformat(), "timestamp": now.isoformat(timespec="seconds"),
                   "retailer": retailer, "product_id": "", "name": p.get("name", ""),
                   "category": p.get("category", ""), "price": "", "was_price": "",
                   "in_stock": "", "status": "no_fetcher"}
            if fetch:
                try:
                    result = fetch(p["url"], debug=(debug and i == 0))
                    for k, v in result.items():
                        if v is not None and (k != "name" or not row["name"]):
                            row[k] = v
                except Exception as e:  # network errors, bad JSON, etc.
                    row["status"] = f"error_{type(e).__name__}"
            if row["status"] == "ok":
                ok += 1
            writer.writerow(row)
            print(f"{row['status']:<14} {row['name'][:50]} {row['price']}")
            if i < len(products) - 1:
                time.sleep(DELAY_SECONDS)

    print(f"\n{ok}/{len(products)} products logged successfully.")
    if products and ok == 0:
        sys.exit(1)  # makes the GitHub Actions run show as failed


if __name__ == "__main__":
    main()
