"""Vega-Lite charts of compared players, built from season rows.

The charts are drawn from the rows GoldRepository.comparison returns, never by
the model, so a mark cannot differ from the data.
"""

from __future__ import annotations

from typing import Any

from scout_backend import ESTIMATE_METRICS, FIGURE_LABELS, figure_fields, ordinal, show_value


SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
# A player with less than one match of minutes has ranges so wide that they
# flatten everyone else's, so he is named in the notes and not drawn.
MIN_CHART_MINUTES = 90
# One colour per player, in this order whoever is compared. Checked for
# separation under colour blindness; three are faint on a light page, which the
# legend and the figures table below every answer make up for.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
MUTED = "#898781"
PERCENTILE_TICKS = [0, 20, 40, 60, 80, 100]


def season_label(season: int) -> str:
    return f"{season}/{(season + 1) % 100:02d}"


def player_labels(rows: list[dict[str, Any]]) -> list[str]:
    """A legend label for each row: the name, an ID if names clash, † for a small sample."""
    names = [str(row.get("player_name") or f"Player {row['player_id']}") for row in rows]
    labels = []
    for row, name in zip(rows, names):
        if names.count(name) > 1:
            name += f" ({row['player_id']})"
        labels.append(name + (" †" if row.get("small_sample") else ""))
    return labels


def statistic_label(field: str) -> str:
    return FIGURE_LABELS[field] + (", %" if field.endswith("_pct") else "")


def group_notes(rows: list[dict[str, Any]], left_out: list[dict[str, Any]]) -> list[str]:
    """Who the players are ranked among, and what a reader must allow for."""
    group, first = rows[0]["detailed_position"], rows[0]
    notes = [f"Ranked among {first['percentile_pool_size']} players listed as {group} with at "
             f"least {first['percentile_pool_min_minutes']:,} minutes, across the five leagues."]
    for row in left_out:
        notes.append(f"{row['player_name']} has under {MIN_CHART_MINUTES} minutes and is not drawn.")
    for row in rows:
        if row["profile_position"] != group:
            notes.append(f"{row['player_name']} is listed as {row['profile_position']} and is "
                         "ranked in this group for the chart.")
    if any(row.get("small_sample") for row in rows):
        notes.append("† Too few minutes for the figures to be reliable.")
    return notes


def title(text: str, notes: list[str]) -> dict[str, Any]:
    return {"text": text, "subtitle": notes, "anchor": "start", "subtitleColor": MUTED,
            "offset": 12}


def colour(labels: list[str]) -> dict[str, Any]:
    return {"field": "player", "type": "nominal", "title": None,
            "scale": {"domain": labels, "range": SERIES[:len(labels)]},
            "legend": {"orient": "top", "symbolType": "circle"}}


def percentile_chart(rows: list[dict[str, Any]], notes: list[str]) -> dict[str, Any]:
    """Each player's percentile on the group's role statistics, one line per statistic."""
    labels = player_labels(rows)
    fields = [field for field in figure_fields(rows[0]["detailed_position"])
              if any(row.get(f"{field}_percentile") is not None for row in rows)]
    values = [
        {"statistic": FIGURE_LABELS[field], "player": label,
         "percentile": row[f"{field}_percentile"],
         "figure": show_value(field, row.get(field)),
         "rank": ordinal(row[f"{field}_percentile"]),
         "range": row.get(f"{field}_range") or "not available",
         "minutes": show_value("minutes", row.get("minutes"))}
        for field in fields for row, label in zip(rows, labels)
        if row.get(f"{field}_percentile") is not None
    ]
    statistic = {"field": "statistic", "type": "nominal", "title": None,
                 "sort": [FIGURE_LABELS[field] for field in fields],
                 "axis": {"labelLimit": 220, "ticks": False, "domain": False, "labelPadding": 8}}
    return {
        "$schema": SCHEMA,
        "title": title(f"Percentile by statistic, {season_label(rows[0]['season'])}", notes),
        "data": {"values": values},
        "width": "container",
        "height": {"step": 34},
        "layer": [
            # The span between the lowest and highest player on a statistic.
            {"mark": {"type": "rule", "color": MUTED, "strokeWidth": 2, "opacity": 0.5},
             "encoding": {"y": statistic,
                          "x": {"aggregate": "min", "field": "percentile", "type": "quantitative"},
                          "x2": {"aggregate": "max", "field": "percentile"}}},
            {"mark": {"type": "point", "filled": True, "size": 150, "opacity": 0.95},
             "encoding": {
                 "y": statistic,
                 "x": {"field": "percentile", "type": "quantitative",
                       "scale": {"domain": [0, 100]},
                       "axis": {"values": PERCENTILE_TICKS, "title": "Percentile (higher is better)"}},
                 "color": colour(labels),
                 "tooltip": [{"field": "player", "title": "Player"},
                             {"field": "statistic", "title": "Statistic"},
                             {"field": "rank", "title": "Percentile"},
                             {"field": "figure", "title": "Figure"},
                             {"field": "range", "title": "Range"},
                             {"field": "minutes", "title": "Minutes"}]}},
        ],
    }


def range_chart(rows: list[dict[str, Any]], notes: list[str]) -> dict[str, Any]:
    """Each player's figure with its range, one panel per statistic on its own scale."""
    labels = player_labels(rows)
    fields = [field for field in figure_fields(rows[0]["detailed_position"])
              if field in ESTIMATE_METRICS and any(row.get(field) is not None for row in rows)]
    values = [
        {"statistic": statistic_label(field), "player": label, "value": row[field],
         "low": row.get(f"{field}_low"), "high": row.get(f"{field}_high"),
         "figure": show_value(field, row[field]),
         "range": row.get(f"{field}_range") or "not available",
         "minutes": show_value("minutes", row.get("minutes"))}
        for field in fields for row, label in zip(rows, labels)
        if row.get(field) is not None
    ]
    player = {"field": "player", "type": "nominal", "sort": labels, "axis": None}
    notes = ["The line is where each player's underlying level probably lies, nine times in "
             "ten. Where two lines overlap, the gap may be chance.", *notes[1:]]
    return {
        "$schema": SCHEMA,
        "title": title(f"Figure and range by statistic, {season_label(rows[0]['season'])}", notes),
        "data": {"values": values},
        "facet": {"row": {"field": "statistic", "type": "nominal", "title": None,
                          "sort": [statistic_label(field) for field in fields],
                          "header": {"labelAngle": 0, "labelAlign": "left", "labelAnchor": "middle",
                                     "labelLimit": 220, "labelPadding": 8}}},
        "spec": {
            "width": 440,
            "height": {"step": 16},
            "layer": [
                {"mark": {"type": "rule", "strokeWidth": 2, "strokeCap": "round"},
                 "encoding": {"y": player,
                              "x": {"field": "low", "type": "quantitative", "title": None,
                                    "scale": {"zero": False, "nice": True},
                                    "axis": {"tickCount": 5}},
                              "x2": {"field": "high"},
                              "color": colour(labels)}},
                {"mark": {"type": "point", "filled": True, "size": 110, "opacity": 1},
                 "encoding": {"y": player,
                              "x": {"field": "value", "type": "quantitative"},
                              "color": colour(labels),
                              "tooltip": [{"field": "player", "title": "Player"},
                                          {"field": "statistic", "title": "Statistic"},
                                          {"field": "figure", "title": "Figure"},
                                          {"field": "range", "title": "Range"},
                                          {"field": "minutes", "title": "Minutes"}]}},
            ],
        },
        # A rate per 90 and a share cannot sit on one scale.
        "resolve": {"scale": {"x": "independent"}},
        "spacing": 10,
    }


def comparison_charts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Both charts for rows from GoldRepository.comparison, with the group they rank in."""
    first = rows[0]
    left_out = [row for row in rows if (row.get("minutes") or 0) < MIN_CHART_MINUTES]
    drawn = [row for row in rows if row not in left_out]
    if len(drawn) < 2:
        raise ValueError(f"Fewer than two of these players have {MIN_CHART_MINUTES} minutes "
                         f"in {season_label(first['season'])}")
    notes = group_notes(drawn, left_out)
    return {
        "group": {"position": first["detailed_position"], "season": first["season"],
                  "players": first["percentile_pool_size"],
                  "min_minutes": first["percentile_pool_min_minutes"]},
        "players": [{"player_id": row["player_id"], "player_name": row["player_name"],
                     "league_id": row["league_id"], "minutes": row["minutes"],
                     "profile_position": row["profile_position"],
                     "small_sample": row["small_sample"]} for row in rows],
        "percentiles": percentile_chart(drawn, notes),
        "ranges": range_chart(drawn, notes),
    }
