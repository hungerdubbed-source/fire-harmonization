import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="MODIS + VIIRS Harmonization", page_icon="🔥", layout="wide")

DATA = Path(__file__).parent 
COLORS = {"MODIS": "#d95f02", "VIIRS": "#1b6ca8"}


@st.cache_data
def load():
    daily = pd.read_csv(DATA / "fire_counts_daily.csv", parse_dates=["date"]).set_index("date")
    weekly = pd.read_csv(DATA / "fire_counts_weekly.csv", parse_dates=["date"]).set_index("date")
    bad = pd.read_csv(DATA / "bad_days.csv", parse_dates=["date"])["date"]
    cells = pd.read_csv(DATA / "strong_cells.csv", parse_dates=["acq_date"])
    summary = json.loads((DATA / "summary.json").read_text())
    overlap = json.loads((DATA / "overlap.json").read_text())
    return daily, weekly, bad, cells, summary, overlap


daily, weekly, bad_days, cells, S, O = load()
bad_set = set(bad_days)

st.title("🔥 MODIS + VIIRS Hot Spot Harmonization")
st.caption("Gujarat (approx. box 20-25°N, 68-75°E) · 1 Nov 2024 to 12 Jan 2025 · MODIS (Terra+Aqua) vs VIIRS (Suomi-NPP) · Data: NASA FIRMS via Kaggle")

st.info(
    f"**Total fire cells match, locations mostly do not.** After harmonization the two sensors report almost the same "
    f"number of fire cells (VIIRS/MODIS = **{S['ratio_good_days']}**), but only **{O['exact_pct_of_modis']}%** of MODIS cells "
    f"have a VIIRS cell in the same 1 km box on the same day ({O['near_pct_of_modis']}% within one box)."
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("VIIRS ÷ MODIS (good days)", S["ratio_good_days"])
c2.metric("Daily correlation", S["daily_corr_good_days"])
c3.metric(f"Weekly correlation ({S['weeks_used']} full weeks)", S["weekly_corr"])
c4.metric("Same box + day overlap", f"{O['exact_pct_of_modis']}%", f"{O['near_pct_of_modis']}% within 1 box", delta_color="off")

# ---------------- sidebar ----------------
st.sidebar.header("Filters")
dmin, dmax = daily.index.min().date(), daily.index.max().date()
start, end = st.sidebar.slider("Date range", dmin, dmax, (dmin, dmax), format="DD MMM YYYY")
sensors = st.sidebar.multiselect("Sensors", ["MODIS", "VIIRS"], default=["MODIS", "VIIRS"])
st.sidebar.caption("Grey bands = days where the VIIRS/MODIS file has missing data (not 'no fire').")

mask = (daily.index >= pd.Timestamp(start)) & (daily.index <= pd.Timestamp(end))
d = daily[mask]

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Daily", "Weekly", "Calendar", "Map", "Method & caveats"])

# ---------------- daily ----------------
with tab1:
    fig = go.Figure()
    plot = d.astype(float).copy()
    plot.loc[plot.index.isin(bad_set)] = float("nan")
    for s in sensors:
        fig.add_trace(go.Scatter(x=plot.index, y=plot[s], mode="lines+markers", name=s,
                                 line=dict(color=COLORS[s]), connectgaps=False))
    # shade bad-day runs
    run = sorted(x for x in d.index if x in bad_set)
    groups, cur = [], []
    for x in run:
        if cur and (x - cur[-1]).days > 1:
            groups.append(cur)
            cur = []
        cur.append(x)
    if cur:
        groups.append(cur)
    for g in groups:
        fig.add_vrect(x0=g[0] - pd.Timedelta(hours=12), x1=g[-1] + pd.Timedelta(hours=12),
                      fillcolor="grey", opacity=0.2, line_width=0)
    fig.update_layout(title="Daily fire cells (after FRP threshold)", yaxis_title="fire cells", xaxis_title=None,
                      height=420, legend_orientation="h", legend_y=1.1)
    st.plotly_chart(fig, width="stretch")
    st.caption("Daily agreement is low (correlation "
               f"{S['daily_corr_good_days']}): the sensors pass at different times and see different clouds.")

# ---------------- weekly ----------------
with tab2:
    w = weekly[(weekly.index >= pd.Timestamp(start)) & (weekly.index <= pd.Timestamp(end) + pd.Timedelta(days=6))]
    fig = go.Figure()
    for s in sensors:
        fig.add_trace(go.Scatter(x=w.index, y=w[s], mode="lines+markers", name=s, line=dict(color=COLORS[s])))
    fig.update_layout(title="Weekly fire cells (full weeks with ≥5 good days)", yaxis_title="fire cells",
                      xaxis_title="week ending", height=420, legend_orientation="h", legend_y=1.1)
    st.plotly_chart(fig, width="stretch")
    st.caption(f"Both sensors stay in the same 30-75 range, but week-to-week ups and downs differ (correlation {S['weekly_corr']} on {S['weeks_used']} weeks, so treat it as weak evidence).")

# ---------------- calendar ----------------
with tab3:
    choice = st.radio("Show", ["MODIS", "VIIRS", "MODIS + VIIRS"], horizontal=True)
    series = d["MODIS"] + d["VIIRS"] if choice == "MODIS + VIIRS" else d[choice]
    series = series.astype(float).copy()
    series[series.index.isin(bad_set)] = float("nan")
    first = series.index.min()
    week0 = first - pd.Timedelta(days=first.weekday())
    idx = pd.DataFrame({"v": series})
    idx["week"] = ((idx.index - week0).days // 7)
    idx["dow"] = idx.index.weekday
    z = idx.pivot(index="dow", columns="week", values="v").reindex(range(7))
    labels = [(week0 + pd.Timedelta(weeks=int(k))).strftime("%d %b") for k in z.columns]
    fig = go.Figure(go.Heatmap(z=z.values, x=labels, y=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                               colorscale="YlOrRd", xgap=3, ygap=3, colorbar_title="fire cells",
                               hoverongaps=False))
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(title=f"Burning activity calendar: {choice}", height=360, xaxis_title="week starting")
    st.plotly_chart(fig, width="stretch")
    st.caption("Blank squares = days excluded because the VIIRS file has missing data (3 to 8 Nov 2024), or days outside the selected range. They are not zero-fire days.")

# ---------------- map ----------------
with tab4:
    day = st.slider("Day", start, end, start, format="DD MMM YYYY", key="mapday")
    show_all = st.checkbox("Show whole selected date range instead of one day", value=False)
    cm = cells[cells["instrument"].isin(sensors)]
    if show_all:
        cm = cm[(cm.acq_date >= pd.Timestamp(start)) & (cm.acq_date <= pd.Timestamp(end))]
    else:
        cm = cm[cm.acq_date == pd.Timestamp(day)]
        if pd.Timestamp(day) in bad_set:
            st.warning("Some satellite data is missing for this day, so counts here are incomplete.")
    st.write(f"**{len(cm)}** fire cells shown")
    if len(cm):
        fig = px.scatter_map(cm, lat="grid_lat", lon="grid_lon", color="instrument", size="frp",
                             size_max=18, color_discrete_map=COLORS, hover_data={"frp": ":.1f", "acq_date": True},
                             zoom=5.6, center={"lat": 22.5, "lon": 71.5}, height=560, opacity=0.7,
                             map_style="carto-positron")
        st.plotly_chart(fig, width="stretch")
    else:
        st.write("No fire cells for this selection.")

# ---------------- method ----------------
with tab5:
    st.markdown(f"""
**Why raw counts mislead.** VIIRS (375 m) gives about 5.6× more points than MODIS (1 km) for the same region
(3,594 vs 641), because one fire is split into several small pixels.

**Steps**
1. Round every point to a ~1 km grid box (2 decimals).
2. Count each (box, day) once (unique fire cells): 620 MODIS vs 2,846 VIIRS.
3. Sum FRP inside each box and keep boxes with FRP ≥ **{S['threshold_frp']}** (MODIS 10th-percentile box FRP): about 501 vs 492 cells on good days.
4. Drop days where a file has missing data ({len(bad_days)} days: 3 to 8 Nov 2024) before comparing.

| | MODIS cells | VIIRS cells |
|---|---|---|
| Good days, after threshold | {O['modis_cells']} | {O['viirs_cells']} |
| Same box + same day | {O['exact_overlap']} | {O['exact_overlap']} |
| Within 1 box | {O['near_overlap']} (of MODIS) | |

**Caveats**
- The threshold is taken from MODIS itself, so about 90% of MODIS cells survive by construction. The comparison that carries information is the VIIRS side (sensitivity: ratio 0.97 / 0.89 / 0.83 at the 5% / 10% / 20% quantile, all days).
- Only one VIIRS satellite (Suomi-NPP); MODIS has Terra and Aqua. Different overpass times explain part of the low overlap.
- Region is a rough box, not Gujarat's real boundary. MODIS file is NRT, not the final archive product.
- `confidence` was harmonised (l/n/h → 27/67/90) but is not used as a filter.
- Weekly correlation uses only {S['weeks_used']} points.
""")
