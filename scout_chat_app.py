"""Run with: streamlit run scout_chat_app.py"""

from __future__ import annotations

import streamlit as st

from scout_api import answer_charts, ask


# Earlier turns sent with each question, matching the limit in scout_api.
HISTORY_TURNS = 20

st.set_page_config(page_title="Scout chat", layout="wide")
st.title("Scout chat")
st.caption("Answers use the gold player season summaries for the five loaded leagues. "
           "They are statistical indicators, with no transfer fees or scout notes.")

if st.sidebar.button("New conversation"):
    st.session_state.turns = []
turns: list[dict] = st.session_state.setdefault("turns", [])


def show_turn(turn: dict) -> None:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])
        charts = turn.get("charts")
        if charts and "note" in charts:
            st.caption(charts["note"])
        elif charts:
            percentiles, ranges = st.tabs(["Percentiles", "Figures and ranges"])
            with percentiles:
                st.vega_lite_chart(charts["percentiles"], use_container_width=True)
            with ranges:
                st.vega_lite_chart(charts["ranges"])
        if turn.get("sources"):
            with st.expander(f"Season rows retrieved ({len(turn['sources'])})"):
                st.dataframe(turn["sources"], use_container_width=True)


for turn in turns:
    show_turn(turn)

question = st.chat_input("Ask about a player, a ranking, or a shortlist for a role")
if question:
    show_turn({"role": "user", "content": question})
    previous = [{"role": turn["role"], "content": turn["content"]}
                for turn in turns[-HISTORY_TURNS:]]
    try:
        with st.spinner("Checking the data..."):
            result = ask(question, previous)
    except Exception as exc:
        st.error(f"The scouting assistant could not answer: {exc}")
        st.stop()
    reply = {"role": "assistant", "content": result["answer"], "sources": result["sources"],
             "charts": answer_charts(result)}
    turns += [{"role": "user", "content": question}, reply]
    show_turn(reply)
