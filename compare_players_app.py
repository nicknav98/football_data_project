"""Run with: streamlit run compare_players_app.py"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from player_comparison import AVERAGE_METRICS, compare_players, metric_columns, read_matchdays


st.set_page_config(page_title="Player comparison", layout="wide")
st.title("Player comparison")
st.caption("Matchday statistics loaded from your S3 bucket")


@st.cache_data(ttl=600, show_spinner="Loading matchday CSVs from S3...")
def load_data() -> tuple[pd.DataFrame, int]:
    return read_matchdays()


if st.sidebar.button("Refresh S3 data"):
    load_data.clear()

try:
    data, file_count = load_data()
except Exception as exc:
    st.error(f"Could not load player data: {exc}")
    st.stop()

st.sidebar.caption(f"{file_count} CSV files loaded. Data refreshes every 10 minutes.")
if "league_id" in data:
    leagues = sorted(data["league_id"].dropna().unique().tolist())
    chosen_leagues = st.sidebar.multiselect("Leagues", leagues, default=leagues)
    data = data[data["league_id"].isin(chosen_leagues)]
if "season" in data:
    seasons = sorted(data["season"].dropna().unique().tolist(), reverse=True)
    chosen_seasons = st.sidebar.multiselect("Seasons", seasons, default=seasons)
    data = data[data["season"].isin(chosen_seasons)]

teams = sorted(data["team_name"].dropna().unique().tolist())
chosen_teams = st.sidebar.multiselect("Teams", teams, default=[])
if chosen_teams:
    data = data[data["team_name"].isin(chosen_teams)]

if "round" in data:
    rounds = sorted(data["round"].dropna().unique().tolist())
    chosen_rounds = st.sidebar.multiselect("Matchdays", rounds, default=[])
    if chosen_rounds:
        data = data[data["round"].isin(chosen_rounds)]

if data.empty:
    st.info("No matches meet these filters.")
    st.stop()

players = (
    data.groupby("player_id", dropna=True)
    .agg(player_name=("player_name", "last"), teams=("team_name", lambda s: ", ".join(sorted(set(s.dropna())))))
    .sort_values("player_name")
)
labels = {int(pid): f"{row.player_name} ({row.teams}) · ID {int(pid)}" for pid, row in players.iterrows()}
player_ids = st.multiselect("Players", list(labels), format_func=lambda pid: labels[pid], max_selections=10)

available = metric_columns(data)
defaults = [c for c in ("goals_total", "goals_assists", "shots_total", "passes_key", "tackles_total", "games_rating") if c in available]
metrics = st.multiselect("Statistics to compare", available, default=defaults)
per_90 = st.toggle("Show counting stats per 90 minutes", value=False)

if not player_ids or not metrics:
    st.info("Choose at least one player and one statistic.")
    st.stop()

summary = compare_players(data, player_ids, metrics, per_90)
summary.index = [labels[int(pid)] for pid in summary.index]
display = summary.T
display.index = [f"{metric} (average)" if metric in AVERAGE_METRICS else f"{metric} / 90" if per_90 and metric not in {"matches", "minutes"} else metric for metric in display.index]
st.dataframe(display.style.format(precision=2, na_rep="N/A"), width="stretch")
st.caption("Matches and minutes are totals. Rating is the mean of available match ratings. Pass accuracy is weighted by passes attempted when available. Missing stats are excluded from averages; per-90 values need minutes played.")
st.download_button("Download comparison CSV", display.to_csv().encode("utf-8"), "player_comparison.csv", "text/csv")
