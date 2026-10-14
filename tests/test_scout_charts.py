import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import scout_api
from scout_backend import ComparisonArgs, GoldRepository
from scout_charts import SERIES, comparison_charts
from tests.test_scout_backend import FakeConnection, FakeCursor


def season_row(player_id, name, profile_position, minutes=2000, small_sample=False, **figures):
    row = {"player_id": player_id, "player_name": name, "league_id": 39, "season": 2025,
           "detailed_position": "Defensive Midfield", "profile_position": profile_position,
           "minutes": minutes, "small_sample": small_sample, "percentile_pool_size": 123,
           "percentile_pool_min_minutes": 1140,
           "tackles_possession_adjusted_per_90": 2.94,
           "tackles_possession_adjusted_per_90_percentile": 87,
           "tackles_possession_adjusted_per_90_low": 2.5,
           "tackles_possession_adjusted_per_90_high": 3.44,
           "tackles_possession_adjusted_per_90_range": "2.50 to 3.44",
           "duel_win_pct": 61.3, "duel_win_pct_percentile": 91, "duel_win_pct_low": 56.9,
           "duel_win_pct_high": 65.5, "duel_win_pct_range": "56.9% to 65.5%",
           "average_rating": 7.33, "average_rating_percentile": 96}
    return {**row, **figures}


GARNER = season_row(4536524, "James Garner", "Defensive Midfield")
SCOTT = season_row(37550443, "Alex Scott", "Central Midfield", minutes=447, small_sample=True,
                   duel_win_pct_percentile=None)


class ChartTests(unittest.TestCase):
    def test_percentile_chart_has_one_mark_per_player_and_statistic_that_was_ranked(self):
        charts = comparison_charts([GARNER, SCOTT])
        chart = charts["percentiles"]
        values = chart["data"]["values"]
        # Scott has no duels percentile, so he has no mark there; rating is not a range.
        self.assertEqual([(value["player"], value["statistic"]) for value in values],
                         [("James Garner", "Tackles /90, adjusted"),
                          ("Alex Scott †", "Tackles /90, adjusted"),
                          ("James Garner", "Duels won"),
                          ("James Garner", "Rating"), ("Alex Scott †", "Rating")])
        self.assertEqual(values[0]["percentile"], 87)
        self.assertEqual(values[0]["figure"], "2.94")
        self.assertEqual(values[0]["range"], "2.50 to 3.44")
        points = chart["layer"][1]["encoding"]
        self.assertEqual(points["x"]["scale"]["domain"], [0, 100])
        self.assertEqual(points["color"]["scale"],
                         {"domain": ["James Garner", "Alex Scott †"], "range": SERIES[:2]})
        notes = chart["title"]["subtitle"]
        self.assertIn("123 players listed as Defensive Midfield with at least 1,140 minutes", notes[0])
        self.assertIn("Alex Scott is listed as Central Midfield and is ranked in this group", notes[1])
        self.assertIn("†", notes[2])
        self.assertEqual(charts["group"], {"position": "Defensive Midfield", "season": 2025,
                                           "players": 123, "min_minutes": 1140})

    def test_range_chart_gives_each_statistic_its_own_scale_and_leaves_rating_out(self):
        chart = comparison_charts([GARNER, SCOTT])["ranges"]
        values = chart["data"]["values"]
        self.assertEqual({value["statistic"] for value in values},
                         {"Tackles /90, adjusted", "Duels won, %"})
        self.assertEqual((values[0]["value"], values[0]["low"], values[0]["high"]), (2.94, 2.5, 3.44))
        self.assertEqual(chart["resolve"], {"scale": {"x": "independent"}})

    def test_a_player_with_almost_no_minutes_is_named_and_not_drawn(self):
        caicedo = season_row(37261500, "Moisés Caicedo", "Defensive Midfield", minutes=14)
        charts = comparison_charts([GARNER, SCOTT, caicedo])
        players = {value["player"] for value in charts["percentiles"]["data"]["values"]}
        self.assertEqual(players, {"James Garner", "Alex Scott †"})
        self.assertIn("Moisés Caicedo has under 90 minutes and is not drawn.",
                      charts["percentiles"]["title"]["subtitle"])
        with self.assertRaises(ValueError):
            comparison_charts([GARNER, caicedo])

    def test_players_with_one_name_are_told_apart(self):
        twin = season_row(7, "James Garner", "Defensive Midfield")
        labels = comparison_charts([GARNER, twin])["percentiles"]["layer"][1]["encoding"]["color"]
        self.assertEqual(labels["scale"]["domain"], ["James Garner (4536524)", "James Garner (7)"])


class ComparisonTests(unittest.TestCase):
    columns = ["player_id", "player_name", "league_id", "season", "detailed_position",
               "profile_position"]

    def compare(self, found, **args):
        capture = []
        repo = GoldRepository(lambda: FakeConnection(capture))
        with patch.object(FakeCursor, "description", [(column,) for column in self.columns]), \
                patch.object(FakeCursor, "fetchall", lambda self: found):
            rows = repo.comparison(ComparisonArgs(season=2025, **args))
        return rows, capture[0]

    def test_everyone_is_ranked_in_the_first_players_position(self):
        found = [(20, "Scott", 39, 2025, "Defensive Midfield", "Central Midfield"),
                 (10, "Garner", 39, 2025, "Defensive Midfield", "Defensive Midfield")]
        rows, (statement, parameters) = self.compare(found, player_ids=[10, 20, 10])
        # In the order asked for, not the order found.
        self.assertEqual([row["player_id"] for row in rows], [10, 20])
        self.assertEqual(parameters, [10, 2025, 10, 20, 2025])
        self.assertIn("detailed_position AS profile_position", statement)
        self.assertIn("WHERE player_id = ? AND season = ?) AS detailed_position", statement)
        # One row a player, from the league he played most in.
        self.assertIn("PARTITION BY player_id", statement)
        # The numbers at each end of a range are kept for the chart.
        self.assertIn("goals_per_90_low", statement)

    def test_a_named_position_is_the_group(self):
        found = [(10, "Garner", 39, 2025, "Central Midfield", "Defensive Midfield"),
                 (20, "Scott", 39, 2025, "Central Midfield", "Central Midfield")]
        _, (statement, parameters) = self.compare(found, player_ids=[10, 20],
                                                  position="Central Midfield")
        self.assertEqual(parameters, ["Central Midfield", 10, 20, 2025])
        self.assertIn("? AS detailed_position", statement)

    def test_players_too_far_apart_or_missing_are_refused_with_a_reason(self):
        kane = [(10, "Garner", 39, 2025, "Defensive Midfield", "Defensive Midfield"),
                (30, "Kane", 82, 2025, "Defensive Midfield", "Centre Forward")]
        with self.assertRaisesRegex(ValueError, "Kane is listed as Centre Forward"):
            self.compare(kane, player_ids=[10, 30])
        with self.assertRaisesRegex(ValueError, "No 2025 season in the data for player 30"):
            self.compare(kane[:1], player_ids=[10, 30])
        with self.assertRaisesRegex(ValueError, "two different players"):
            self.compare(kane, player_ids=[10, 10])
        coach = [(10, "Garner", 39, 2025, "Coach", "Defensive Midfield"),
                 (20, "Scott", 39, 2025, "Coach", "Central Midfield")]
        with self.assertRaisesRegex(ValueError, "must be a playing position"):
            self.compare(coach, player_ids=[10, 20], position="Coach")


class FakeComparison:
    def comparison(self, args):
        if 30 in args.player_ids:
            raise ValueError("Kane is listed as Centre Forward, which is too far")
        if 40 in args.player_ids:
            raise RuntimeError("warehouse stopped")
        return [GARNER, SCOTT]


class ChartRouteTests(unittest.TestCase):
    def setUp(self):
        scout_api.app.dependency_overrides[scout_api.repository] = FakeComparison
        self.addCleanup(scout_api.app.dependency_overrides.clear)
        self.enterContext(patch.dict(os.environ, {"SCOUT_API_KEY": "private-token"}))
        self.client = TestClient(scout_api.app)
        self.key = {"X-Scout-API-Key": "private-token"}

    def test_chart_route_needs_the_key_and_explains_a_refusal(self):
        route = "/charts/compare?player_ids=4536524&player_ids=37550443&season=2025"
        self.assertEqual(self.client.get(route).status_code, 401)
        body = self.client.get(route, headers=self.key).json()
        self.assertEqual(sorted(body), ["group", "percentiles", "players", "ranges"])
        self.assertEqual(body["players"][1]["profile_position"], "Central Midfield")
        refused = self.client.get("/charts/compare?player_ids=10&player_ids=30&season=2025",
                                  headers=self.key)
        self.assertEqual(refused.status_code, 422)
        self.assertIn("Centre Forward", refused.json()["detail"])
        self.assertEqual(self.client.get("/charts/compare?player_ids=10&season=2025",
                                         headers=self.key).status_code, 422)
        self.assertEqual(self.client.get("/charts/compare?player_ids=10&player_ids=40&season=2025",
                                         headers=self.key).status_code, 503)

    def test_an_answer_gets_charts_only_for_several_players_in_one_season(self):
        def result(*rows):
            sources = [{"source_id": f"{player}:39:{season}", "player_id": player, "season": season}
                       for player, season in rows]
            return {"sources": sources, "used_sources": [row["source_id"] for row in sources]}

        with patch.object(scout_api, "repository", return_value=FakeComparison()):
            self.assertIn("percentiles", scout_api.answer_charts(result((10, 2025), (20, 2025))))
            # One player, or seasons that differ, is not a comparison to draw.
            self.assertIsNone(scout_api.answer_charts(result((10, 2025), (10, 2024))))
            self.assertIsNone(scout_api.answer_charts(result((10, 2025), (20, 2024))))
            self.assertIsNone(scout_api.answer_charts({"answer": "No data", "sources": []}))
            # A retrieved row the answer did not use is not charted.
            unused = result((10, 2025), (20, 2025))
            unused["used_sources"] = unused["used_sources"][:1]
            self.assertIsNone(scout_api.answer_charts(unused))
            note = scout_api.answer_charts(result((10, 2025), (30, 2025)))
            self.assertEqual(note, {"note": "No chart: Kane is listed as Centre Forward, "
                                            "which is too far."})
            # A chart that fails must not take the answer with it.
            with self.assertLogs("scout_backend", level="WARNING"):
                self.assertIsNone(scout_api.answer_charts(result((10, 2025), (40, 2025))))


if __name__ == "__main__":
    unittest.main()
