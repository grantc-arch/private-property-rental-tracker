# Was that Black Friday deal real?

Daily price logger for a study of South African Black Friday discounts.

## Setup
1. Create a GitHub repo and push these files.
2. Edit `USER_AGENT` in `log_prices.py` with your real contact email.
3. Fill `products.csv` (30-50 products, several categories). Use full product
   page URLs; for Takealot the URL must contain the `PLID` number.
4. Run locally once: `pip install -r requirements.txt && python log_prices.py --debug`
   Check that prices are captured. If they show `parse_error`, adjust
   `parse_takealot()` using the JSON printed by `--debug`.
5. Push, then run the workflow manually from the Actions tab to confirm it
   commits `data/prices.csv`. After that it runs daily.

## Definitions (fix these before you see results)
- Genuine deal: Black Friday price is below the lowest price in the prior 30 days.
- Inflated "was" price: the advertised was-price never appeared as the selling price.

## Ethics
Check each retailer's terms, one pass a day, honest User-Agent, stop if blocked.
Describe findings as being about your tracked basket, not the whole retailer.
