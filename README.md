# PrivateProperty Rental Watcher — Stellenbosch

Automated rental listing watcher for PrivateProperty.co.za, scoped to Stellenbosch.
Built on the same architecture as an existing Property24 watcher: Playwright fetch ->
BeautifulSoup parse -> dedupe against a seen-listings file -> Telegram alert on anything new.
Runs on a schedule via GitHub Actions, no server required.

## Status

Selectors in `privateproperty_scraper.py` are marked `# CONFIRM` and have not yet been
verified against PrivateProperty's live markup — this needs to be done before the bot
will parse real listings. See Setup below.

## How it works

1. GitHub Actions runs `privateproperty_scraper.py` on a schedule (hourly by default).
2. The script loads the search results page with Playwright (handles JS-rendered content).
3. BeautifulSoup parses each listing card into id, title, price, beds, address, url.
4. New listing IDs (not in `seen_privateproperty.json`) trigger a Telegram message.
5. The updated seen-list is committed back to the repo so state persists between runs.

## Setup

1. Clone this repo and install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install --with-deps chromium
   ```
2. Open the search URL in `privateproperty_scraper.py` in a browser, inspect a listing
   card, and replace the `# CONFIRM` selectors with the real ones.
3. Create a Telegram bot via @BotFather, get your bot token and chat ID.
4. In the GitHub repo: Settings -> Secrets and variables -> Actions, add:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. Push to `main` — the workflow in `.github/workflows/rental_watch_privateproperty.yml`
   will start running on its schedule, or trigger it manually via the Actions tab
   ("Run workflow").

## Repo structure

```
.
├── privateproperty_scraper.py
├── requirements.txt
├── .gitignore
├── README.md
└── .github/
    └── workflows/
        └── rental_watch_privateproperty.yml
```
