# W3Schools Scraper

FastAPI app that uses Playwright and BeautifulSoup to scrape W3Schools tutorial content.

## Features

- Discovers W3Schools tutorial languages dynamically
- Scrapes tutorial topic lists from the left sidebar
- Scrapes page headings, paragraphs, and code examples
- Exposes a FastAPI API with Swagger docs
- Exports scraped results to JSON

## Requirements

- Windows 10
- Python 3.13
- Virtual environment already set up

## Install

```bash
pip install -r requirements.txt
playwright install chromium
```

## Run

Use this on Windows:

```bash
python main.py
```

Do not use `uvicorn --reload` here. `main.py` sets the Windows Proactor event loop policy so Playwright can launch Chromium correctly.

## Render

If you deploy this on Render, Playwright itself is not enough. Chromium must also be installed.

This app now checks for the browser at startup and runs:

```bash
python -m playwright install chromium
```

if the Chromium binary is missing.

If you want faster deploys, put the install in your Render build command too:

```bash
pip install -r requirements.txt && python -m playwright install chromium
```

## Open API Docs

- Swagger UI: `http://127.0.0.1:8000/docs`
- Root info: `http://127.0.0.1:8000/`

## API Endpoints

- `GET /languages`
  - Lists discovered W3Schools tutorial languages and tutorial roots
- `GET /scrape/{lang}/topics`
  - Lists tutorial pages for one language without scraping every page
- `GET /scrape/{lang}/first`
  - Scrapes the first discovered page for a quick test
- `GET /scrape/{lang}/page?url=https://...`
  - Scrapes one specific page
- `GET /scrape/{lang}?limit=N`
  - Scrapes pages for one language
- `GET /scrape/all`
  - Scrapes every discovered language
- `GET /export/{lang}?limit=N`
  - Scrapes and saves results to `{lang}_full.json`

## Recommended Test Order

1. `GET /languages`
2. `GET /scrape/python/first`
3. `GET /scrape/python/topics`
4. `GET /scrape/python?limit=5`
5. `GET /export/python`

## Example Slugs

The exact list comes from `GET /languages`, but common examples include:

- `html`
- `python`
- `java`
- `php`
- `go`
- `rust`
- `typescript`
- `python-numpy`
- `python-pandas`

## Notes

- Full scrapes can take a long time.
- W3Schools may change its page structure, which can affect sidebar discovery.
- The Windows asyncio policy in `main.py` currently works, even though Python 3.13 shows a deprecation warning.
