"""Checks for bounded SQL access and evidence returned by the assistant."""

from decimal import Decimal
from types import SimpleNamespace
import unittest

from scout_backend import GoldRepository, LeaderboardArgs, ScoutAssistant


class FakeCursor:
    description = [("player_id",), ("league_id",), ("season",), ("goals_per_90",)]

    def __init__(self, capture):
        self.capture = capture

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, statement, parameters):
        self.capture.append((statement, parameters))

    def fetchall(self):
        return [(10, 39, 2025, Decimal("0.57"))]


class FakeConnection:
    def __init__(self, capture):
        self.capture = capture

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def cursor(self):
        return FakeCursor(self.capture)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.capture = []
        self.repo = GoldRepository(lambda: FakeConnection(self.capture))

    def test_search_uses_bound_literal_name(self):
        rows = self.repo.search_players("O'Brien%", 3)
        statement, parameters = self.capture[0]
        self.assertNotIn("O'Brien", statement)
        self.assertEqual(parameters, ["O'Brien%", 3])
        self.assertEqual(rows[0]["goals_per_90"], 0.57)

    def test_leaderboard_allows_only_known_metric(self):
        with self.assertRaises(ValueError):
            self.repo.leaderboard(LeaderboardArgs(
                metric="goals_per_90; DROP TABLE x", league_id=None,
                season=None, min_minutes=450, limit=10,
            ))
        self.assertEqual(self.capture, [])

    def test_leaderboard_binds_filters_and_limit(self):
        self.repo.leaderboard(LeaderboardArgs(
            metric="goals_per_90", league_id=39,
            season=2025, min_minutes=900, limit=5,
        ))
        statement, parameters = self.capture[0]
        self.assertIn("ORDER BY goals_per_90 DESC", statement)
        self.assertIn("goals_observed_minutes >= ?", statement)
        self.assertEqual(parameters, [900, 900, 39, 2025, 5])

    def test_ratio_ranking_requires_observed_attempts(self):
        self.repo.leaderboard(LeaderboardArgs(
            metric="pass_accuracy_pct", league_id=None,
            season=None, min_minutes=450, limit=5,
        ))
        statement, parameters = self.capture[0]
        self.assertIn("passes_with_accuracy >= ?", statement)
        self.assertEqual(parameters, [450, 100, 5])


class FakeResponses:
    def __init__(self, answer="Ten scored 0.57 per 90 [10:39:2025]."):
        self.requests = []
        self.answer = answer

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) == 1:
            call = SimpleNamespace(type="function_call", name="player_seasons",
                                   arguments='{"player_id":10}', call_id="call_1")
            return SimpleNamespace(output=[call], output_text="")
        return SimpleNamespace(output=[], output_text=self.answer)


class AssistantTests(unittest.TestCase):
    def test_answer_includes_retrieved_season_and_limits_model_tools(self):
        capture = []
        responses = FakeResponses()
        client = SimpleNamespace(responses=responses)
        assistant = ScoutAssistant(GoldRepository(lambda: FakeConnection(capture)),
                                   client, "configured-model")

        result = assistant.ask("How did player 10 score?")

        self.assertEqual(result["sources"][0]["source_id"], "10:39:2025")
        self.assertEqual(result["sources"][0]["goals_per_90"], 0.57)
        self.assertEqual(responses.requests[0]["tool_choice"], "required")
        self.assertFalse(responses.requests[0]["store"])
        self.assertEqual(responses.requests[1]["tool_choice"], "auto")

    def test_answer_rejects_unretrieved_citation(self):
        client = SimpleNamespace(responses=FakeResponses("Claim [99:39:2025]."))
        assistant = ScoutAssistant(GoldRepository(lambda: FakeConnection([])),
                                   client, "configured-model")
        with self.assertRaisesRegex(RuntimeError, "cite retrieved"):
            assistant.ask("How did player 10 score?")


if __name__ == "__main__":
    unittest.main()
