from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import ccxt
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

TITLE = "Hyperliquid Big Trader Monitor"


def _utc_ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def _public_info(exchange: ccxt.Exchange, payload: Dict[str, Any]) -> Any:
    if hasattr(exchange, "public_post_info"):
        return exchange.public_post_info(payload)
    return exchange.request("info", "public", "POST", payload)


@st.cache_data(ttl=30)
def fetch_recent_fills(
    address: str, start_ms: int, end_ms: int, aggregate_by_time: bool
) -> List[Dict[str, Any]]:
    exchange = ccxt.hyperliquid({"enableRateLimit": True})
    payload = {
        "type": "userFillsByTime",
        "user": address,
        "startTime": start_ms,
        "endTime": end_ms,
        "aggregateByTime": aggregate_by_time,
    }
    return _public_info(exchange, payload)


@st.cache_data(ttl=30)
def fetch_positions_single(address: str) -> Dict[str, Any]:
    exchange = ccxt.hyperliquid({"enableRateLimit": True})
    payload = {
        "type": "clearinghouseState",
        "user": address,
    }
    return _public_info(exchange, payload)


st.set_page_config(page_title=TITLE, layout="wide")

st.title(TITLE)

st.markdown(
    "Read-only dashboard for recent fills (last 24 hours) and active positions of large traders."
)

st.markdown(
    """
<style>
    :root {
        --bg: #0b0f14;
        --panel: #121821;
        --panel-2: #0f141c;
        --text: #e6edf3;
        --muted: #9aa4b2;
        --accent: #4fd1c5;
        --accent-2: #f6ad55;
        --border: #1f2a37;
    }
    .stApp {
        background: radial-gradient(1200px 500px at 20% 0%, #121a24, var(--bg));
        color: var(--text);
    }
    h1, h2, h3, h4, h5 {
        color: var(--text);
        font-family: "IBM Plex Sans", "SF Pro Text", sans-serif;
        letter-spacing: 0.2px;
    }
    .block-container {
        padding-top: 2.2rem;
        padding-bottom: 3rem;
    }
    .stSidebar {
        background: linear-gradient(180deg, #0f141c 0%, #0b0f14 100%);
        border-right: 1px solid var(--border);
    }
    .stSidebar [data-testid="stMarkdownContainer"] {
        color: var(--muted);
    }
    .stTextInput > div > div > input,
    .stTextArea textarea,
    .stNumberInput input {
        background: var(--panel);
        color: var(--text);
        border: 1px solid var(--border);
    }
    .stSelectbox > div > div {
        background: var(--panel);
        border: 1px solid var(--border);
    }
    .stButton > button {
        background: var(--panel);
        color: var(--text);
        border: 1px solid var(--border);
        border-radius: 8px;
    }
    .stButton > button:hover {
        border-color: var(--accent);
        color: var(--accent);
    }
    .metric-card {
        background: linear-gradient(180deg, var(--panel) 0%, var(--panel-2) 100%);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 14px 16px;
    }
    .metric-label {
        color: var(--muted);
        font-size: 0.85rem;
    }
    .metric-value {
        font-size: 1.3rem;
        font-weight: 600;
    }
    [data-testid="stDataFrame"] {
        border: 1px solid var(--border);
        border-radius: 12px;
        overflow: hidden;
    }
</style>
""",
    unsafe_allow_html=True,
)

st.sidebar.header("Inputs")

if "wallet_entries" not in st.session_state:
    st.session_state["wallet_entries"] = [
        {"label": "Trader 1", "address": ""},
    ]

st.sidebar.markdown("**Tracked traders**")

for idx, entry in enumerate(st.session_state["wallet_entries"]):
    cols = st.sidebar.columns([2, 3, 1])
    with cols[0]:
        entry["label"] = st.text_input(
            f"Label {idx+1}",
            value=entry.get("label", f"Trader {idx+1}"),
            key=f"label_{idx}",
        )
    with cols[1]:
        entry["address"] = st.text_input(
            f"Address {idx+1}",
            value=entry.get("address", ""),
            placeholder="0xabc...",
            key=f"address_{idx}",
        )
    with cols[2]:
        if st.button("Remove", key=f"remove_{idx}"):
            st.session_state["wallet_entries"].pop(idx)
            st.rerun()

if st.sidebar.button("Add trader"):
    st.session_state["wallet_entries"].append(
        {"label": f"Trader {len(st.session_state['wallet_entries']) + 1}", "address": ""}
    )
    st.rerun()

upload = st.sidebar.file_uploader(
    "Upload wallet list (txt or csv)",
    type=["txt", "csv"],
    help="One address per line or a single column CSV.",
)

if upload is not None:
    raw = upload.getvalue().decode("utf-8", errors="ignore")
    tokens = []
    for line in raw.splitlines():
        for item in line.split(","):
            val = item.strip()
            if val:
                tokens.append(val)
    for addr in tokens:
        st.session_state["wallet_entries"].append(
            {"label": f"Trader {len(st.session_state['wallet_entries']) + 1}", "address": addr}
        )
    st.rerun()

max_fills = st.sidebar.number_input(
    "Max fills per trader",
    min_value=10,
    max_value=2000,
    value=200,
    step=10,
)

aggregate_by_time = st.sidebar.checkbox(
    "Aggregate fills by time",
    value=False,
    help="Combine partial fills when a crossing order hits multiple resting orders.",
)

window_hours = st.sidebar.slider(
    "Fill window (hours)",
    min_value=1,
    max_value=24,
    value=24,
    step=1,
)

refresh = st.sidebar.button("Refresh now")

auto_refresh = st.sidebar.checkbox("Auto refresh", value=True)
refresh_seconds = st.sidebar.selectbox(
    "Refresh interval (seconds)",
    options=[5, 10, 15, 30, 60, 120],
    index=3,
)

def _parse_entries(entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    cleaned = []
    for item in entries:
        addr = (item.get("address") or "").strip()
        label = (item.get("label") or "").strip()
        if addr:
            cleaned.append({"address": addr, "label": label or addr})
    return cleaned

entries = _parse_entries(st.session_state["wallet_entries"])
addresses = [e["address"] for e in entries]
labels_by_address = {e["address"]: e["label"] for e in entries}

if auto_refresh and addresses:
    st_autorefresh(interval=refresh_seconds * 1000, key="auto_refresh")

if refresh:
    st.cache_data.clear()

if not addresses:
    st.warning("Add at least one trader address in the sidebar to load data.")
    st.stop()

end_dt = datetime.now(tz=timezone.utc)
start_dt = end_dt - timedelta(hours=int(window_hours))
start_ms = _utc_ms(start_dt)
end_ms = _utc_ms(end_dt)

summary_cols = st.columns(3)
with summary_cols[0]:
    st.markdown(
        f"""
<div class="metric-card">
  <div class="metric-label">Tracking</div>
  <div class="metric-value">{len(addresses)} traders</div>
</div>
""",
        unsafe_allow_html=True,
    )
with summary_cols[1]:
    st.markdown(
        f"""
<div class="metric-card">
  <div class="metric-label">Window</div>
  <div class="metric-value">{window_hours} hours</div>
</div>
""",
        unsafe_allow_html=True,
    )
with summary_cols[2]:
    st.markdown(
        f"""
<div class="metric-card">
  <div class="metric-label">UTC Range</div>
  <div class="metric-value">{start_dt.strftime('%m/%d %H:%M')} → {end_dt.strftime('%m/%d %H:%M')}</div>
</div>
""",
        unsafe_allow_html=True,
    )

st.caption(f"Window: {start_dt.isoformat()} to {end_dt.isoformat()} (UTC)")

# Section 1: Recent fills
st.subheader(f"Recent Fills (Last {window_hours} Hours)")

fills_rows: List[Dict[str, Any]] = []
for addr in addresses:
    try:
        fills = fetch_recent_fills(addr, start_ms, end_ms, aggregate_by_time) or []
    except Exception as exc:
        st.error(f"Failed to load fills for {addr}: {exc}")
        continue

    for fill in fills[: int(max_fills)]:
        ts = fill.get("time") or fill.get("timestamp")
        ts_ms = _safe_float(ts) if ts is not None else float("nan")
        dt = (
            datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            if ts_ms == ts_ms
            else None
        )
        px = _safe_float(fill.get("px"))
        sz = _safe_float(fill.get("sz"))
        fills_rows.append(
            {
                "time": dt.isoformat() if dt else "",
                "label": labels_by_address.get(addr, addr),
                "trader": addr,
                "coin": fill.get("coin"),
                "side": fill.get("side"),
                "dir": fill.get("dir"),
                "price": px,
                "size": sz,
                "notional": px * sz if px == px and sz == sz else float("nan"),
                "closed_pnl": _safe_float(fill.get("closedPnl")),
                "fee": _safe_float(fill.get("fee")),
                "liquidation": fill.get("liquidation"),
            }
        )

if fills_rows:
    fills_df = pd.DataFrame(fills_rows)
    fills_df = fills_df.sort_values(by="time", ascending=False)
    st.dataframe(fills_df, use_container_width=True, hide_index=True)
else:
    st.info(
        f"No fills found in the last {window_hours} hours for the provided addresses."
    )

# Section 2: Active positions
st.subheader("Active Positions")

positions_rows: List[Dict[str, Any]] = []

for addr in addresses:
    try:
        state = fetch_positions_single(addr)
    except Exception as exc:
        st.error(f"Failed to load positions for {addr}: {exc}")
        continue
    asset_positions = (state or {}).get("assetPositions") or []
    for ap in asset_positions:
        pos = ap.get("position", {})
        szi = _safe_float(pos.get("szi"))
        if szi == 0:
            continue
        positions_rows.append(
            {
                "label": labels_by_address.get(addr, addr),
                "trader": addr,
                "coin": pos.get("coin"),
                "size": szi,
                "entry_px": _safe_float(pos.get("entryPx")),
                "position_value": _safe_float(pos.get("positionValue")),
                "unrealized_pnl": _safe_float(pos.get("unrealizedPnl")),
                "return_on_equity": _safe_float(pos.get("returnOnEquity")),
                "liquidation_px": _safe_float(pos.get("liquidationPx")),
                "margin_used": _safe_float(pos.get("marginUsed")),
                "leverage_type": pos.get("leverage", {}).get("type"),
                "leverage_value": _safe_float(pos.get("leverage", {}).get("value")),
            }
        )

if positions_rows:
    positions_df = pd.DataFrame(positions_rows)
    positions_df = positions_df.sort_values(by=["trader", "coin"], ascending=True)
    st.dataframe(positions_df, use_container_width=True, hide_index=True)
else:
    st.info("No active positions found for the provided addresses.")

st.caption("Data source: Hyperliquid public API via ccxt.")
