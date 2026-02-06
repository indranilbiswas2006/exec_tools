# Hyperliquid Big Trader Monitor

Read-only Streamlit dashboard showing recent fills (last 24 hours) and active positions for a list of trader addresses on Hyperliquid.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Notes

- Enter trader addresses (one per line) in the sidebar.
- Data is sourced from Hyperliquid public endpoints via ccxt.
