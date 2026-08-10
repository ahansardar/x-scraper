# X GraphQL Scraper

Local Python scripts for collecting X Explore and SearchTimeline GraphQL responses with an authorized web session.

## Setup

Copy `.env.example` to `.env` and fill in:

```env
X_AUTH_TOKEN=
X_CT0=
X_BEARER=
```

## Search

Edit `DEFAULT_KEYWORDS` in `graphql_search.py`, then run:

```powershell
python -u .\graphql_search.py
```

Or pass keywords directly:

```powershell
python .\graphql_search.py india "#bengaluru" --max-pages 3
```

Results are written to `x_search_results.csv`; raw debug payloads are written to `debug_search/`.

## Explore

```powershell
python -u .\graphql.py
```

Results are written to `x_explore.csv`.
