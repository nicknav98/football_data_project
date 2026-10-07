"""Checks for bounded SQL access and evidence returned by the assistant."""

from decimal import Decimal
import re
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from openai import OpenAI

from scout_backend import (
    GoldRepository, LeaderboardArgs, MAX_TOOL_CALLS, MODEL_OUTPUT_TOKENS,
    MODEL_RETRY_OUTPUT_TOKENS, RANK_METRICS, ROLE_PROFILES, ScoutAssistant, ShortlistArgs,
    figures_table, fill_markers, show_value, typed_figures,
)


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
        self.assertEqual(parameters, ["O'Brien%", "o'brien%", 3])
        self.assertEqual(rows[0]["goals_per_90"], 0.57)

    def test_name_search_matches_spacing_and_full_names_against_initials(self):
        # Execute the generated search SQL against named fixture rows, including
        # bound parameters. SQLite supplies the two Spark string functions here.
        with sqlite3.connect(":memory:") as connection:
            connection.row_factory = sqlite3.Row
            connection.create_function("contains", 2, lambda value, part: part in value)
            connection.create_function("regexp_replace", 3,
                                       lambda value, pattern, replacement:
                                       re.sub(pattern, replacement, value))
            connection.execute("""CREATE TABLE players (
                player_id INTEGER, player_name TEXT, profile_age INTEGER,
                nationality TEXT, first_season_in_data INTEGER,
                last_season_in_data INTEGER, leagues_in_data TEXT,
                appearances INTEGER, minutes INTEGER)""")
            connection.executemany("INSERT INTO players VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                (10, "J. Garner", 25, "England", 2024, 2026, "39", 10, 900),
                (11, "R. Lavia", 22, "Belgium", 2024, 2026, "39", 10, 900),
            ])
            def query(statement, parameters):
                return [dict(row) for row in connection.execute(statement, parameters)]

            with patch("scout_backend.GOLD_OBSERVED", "players"), \
                    patch.object(self.repo, "_query", side_effect=query):
                for name, expected_id in (("J.Garner", 10), ("James Garner", 10),
                                          ("Romeo Lavia", 11), ("Lavia", 11)):
                    with self.subTest(name=name):
                        self.assertEqual([row["player_id"] for row in
                                          self.repo.search_players(name)], [expected_id])
                self.assertEqual(self.repo.search_players("Nobody"), [])
                self.assertEqual(self.repo.search_players("Garner' OR 1=1"), [])
                self.assertEqual(self.repo.search_players(".."), [])

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

    def test_shortlist_allows_only_known_role(self):
        with self.assertRaises(ValueError):
            self.repo.shortlist(ShortlistArgs(
                role="defensive_mid; DROP TABLE x", season=2025, league_id=None,
                max_age=None, min_minutes=1500, exclude_team=None, limit=10,
            ))
        self.assertEqual(self.capture, [])

    def test_shortlist_ranks_whole_pool_then_binds_filters(self):
        self.repo.shortlist(ShortlistArgs(
            role="defensive_mid", season=2025, league_id=39, max_age=23,
            min_minutes=1500, exclude_team="Chelsea'", limit=5,
        ))
        statement, parameters = self.capture[0]
        pool, output = statement.split("FROM ranked")
        self.assertIn("percent_rank() OVER (ORDER BY tackles_possession_adjusted_per_90)", pool)
        self.assertNotIn("league_id = ?", pool)
        self.assertIn("detailed_position IN (?)", pool)
        self.assertNotIn("Chelsea", statement)
        self.assertEqual(parameters, [2025, "Defensive Midfield", 1500, 39, 23, "Chelsea'", 5])

    def test_shortlist_without_filters_is_valid_sql(self):
        self.repo.shortlist(ShortlistArgs(
            role="striker", season=2025, league_id=None, max_age=None,
            min_minutes=900, exclude_team=None, limit=10,
        ))
        statement, parameters = self.capture[0]
        self.assertIn("WHERE TRUE", statement)
        self.assertEqual(parameters, [2025, "Centre Forward", "Secondary Striker", 900, 10])

    def test_player_seasons_ranks_each_metric_within_position_and_season(self):
        self.repo.player_seasons(10)
        statement, parameters = self.capture[0]
        self.assertEqual(parameters, [10])
        pool = statement.split("FROM player p")[1].split("GROUP BY")[0]
        self.assertIn("q.season = p.season", pool)
        self.assertIn("q.detailed_position = p.detailed_position", pool)
        self.assertIn("q.minutes >= q.pool_min_minutes", pool)
        self.assertNotIn("league_id", pool)
        for metric in RANK_METRICS | {"passes_per_90"}:
            self.assertEqual(statement.count(f"AS {metric}_percentile"), 1, metric)
        # Passes per 90 is not in gold; a season with no minutes must not fail.
        self.assertIn("try_divide(passes_attempted * 90.0, minutes)", statement)
        # A percentage from too few attempts is left unranked on both sides.
        self.assertIn("p.passes_with_accuracy >= 100 AND q.passes_with_accuracy >= 100", statement)

    def test_role_weights_sum_to_one(self):
        for role, profile in ROLE_PROFILES.items():
            self.assertAlmostEqual(sum(profile["weights"].values()), 1.0, msg=role)


class FakeResponses:
    def __init__(self, answer="Ten scored {10:39:2025 goals_per_90} per 90."):
        self.requests = []
        self.answer = answer

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) == 1:
            call = SimpleNamespace(type="function_call", name="player_seasons",
                                   arguments='{"player_id":10}', call_id="call_1")
            return SimpleNamespace(output=[call], output_text="")
        return SimpleNamespace(output=[], output_text=self.answer)


def function_response(name="player_seasons", arguments='{"player_id":10}', call_id="call_1"):
    return SimpleNamespace(status="completed", output_text="", output=[
        SimpleNamespace(type="function_call", name=name, arguments=arguments, call_id=call_id)
    ])


def text_response(answer="Ten scored {10:39:2025 goals_per_90} per 90."):
    return SimpleNamespace(status="completed", output=[], output_text=answer)


def incomplete_response(reason="max_output_tokens", output=None, answer=""):
    return SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason=reason),
                           output=output or [], output_text=answer)


class ScriptedResponses:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append({**kwargs, "input": list(kwargs["input"])})
        return next(self.responses)


class AssistantTests(unittest.TestCase):
    def scripted_assistant(self, *responses, repository=None):
        model = ScriptedResponses(*responses)
        repository = repository or GoldRepository(lambda: FakeConnection([]))
        return ScoutAssistant(repository, SimpleNamespace(responses=model), "configured-model"), model

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
        self.assertEqual(responses.requests[0]["max_output_tokens"], MODEL_OUTPUT_TOKENS)
        self.assertEqual(responses.requests[1]["tool_choice"], "auto")

    def test_low_reasoning_is_sent_only_to_supported_original_gpt5_models(self):
        for model_name, expected in (("gpt-5-nano", {"effort": "low"}),
                                     ("gpt-5-nano-2025-08-07", {"effort": "low"}),
                                     ("gpt-4.1", None), ("gpt-5-pro", None)):
            with self.subTest(model=model_name):
                assistant, model = self.scripted_assistant(function_response(), text_response())
                assistant.model = model_name
                self.assertTrue(assistant.ask("How did player 10 score?")["answer"])
                for request in model.requests:
                    self.assertEqual(request.get("reasoning"), expected)

    def test_reasoning_effort_setting_is_sent_and_widens_the_output_budget(self):
        with patch.dict("os.environ", {"SCOUT_REASONING_EFFORT": " Medium "}):
            assistant, model = self.scripted_assistant(
                function_response(), incomplete_response(), text_response())
            assistant.model = "gpt-5-mini"
            with self.assertLogs("scout_backend", level="INFO") as logs:
                self.assertTrue(assistant.ask("How did player 10 score?")["answer"])
        self.assertEqual([request["reasoning"] for request in model.requests],
                         [{"effort": "medium"}] * 3)
        self.assertEqual([request["max_output_tokens"] for request in model.requests],
                         [2 * MODEL_OUTPUT_TOKENS, 2 * MODEL_OUTPUT_TOKENS,
                          2 * MODEL_RETRY_OUTPUT_TOKENS])
        self.assertIn("effort=medium", logs.output[0])

    def test_unknown_reasoning_effort_is_refused_before_any_request(self):
        with patch.dict("os.environ", {"SCOUT_REASONING_EFFORT": "maximum"}):
            assistant, model = self.scripted_assistant(function_response())
            with self.assertRaisesRegex(RuntimeError, "SCOUT_REASONING_EFFORT"):
                assistant.ask("How did player 10 score?")
        self.assertEqual(model.requests, [])

    def test_openai_read_timeout_is_identified_without_repeating_the_request(self):
        requests = []
        def timed_out(request):
            requests.append(request)
            raise httpx.ReadTimeout("Synthetic timeout", request=request)

        # Use the real SDK against a local mock transport. No network or keys.
        with httpx.Client(transport=httpx.MockTransport(timed_out)) as transport:
            client = OpenAI(api_key="fixture-key", http_client=transport,
                            timeout=120, max_retries=0)
            assistant = ScoutAssistant(Mock(), client, "gpt-5-nano")
            with self.assertLogs("scout_backend", level="WARNING") as logs:
                with self.assertRaisesRegex(RuntimeError, "OpenAI model request timed out"):
                    assistant.ask("How did player 10 score?")
            self.assertEqual(len(requests), 1)
            self.assertIn("Scout OpenAI request timed out", logs.output[0])

    def test_initial_truncation_retries_before_declaring_no_data(self):
        assistant, model = self.scripted_assistant(
            incomplete_response(), function_response(), text_response())
        result = assistant.ask("How is J.Garner doing?")
        self.assertEqual(result["sources"][0]["source_id"], "10:39:2025")
        self.assertEqual([request["max_output_tokens"] for request in model.requests],
                         [MODEL_OUTPUT_TOKENS, MODEL_RETRY_OUTPUT_TOKENS, MODEL_OUTPUT_TOKENS])
        self.assertEqual(model.requests[0]["input"], model.requests[1]["input"])
        self.assertEqual(model.requests[1]["tool_choice"], "required")

    def test_final_truncation_retries_without_rerunning_data_lookup(self):
        repository = Mock()
        repository.player_seasons.return_value = [
            {"player_id": 10, "league_id": 39, "season": 2025, "goals_per_90": 0.57}
        ]
        assistant, model = self.scripted_assistant(
            function_response(), incomplete_response(), text_response(), repository=repository)
        self.assertTrue(assistant.ask("How did player 10 score?")["answer"])
        repository.player_seasons.assert_called_once_with(10)
        self.assertEqual(model.requests[1]["input"], model.requests[2]["input"])

    def test_partial_tool_arguments_are_discarded_before_retry(self):
        partial = function_response(arguments='{"player_id":').output
        assistant, model = self.scripted_assistant(
            incomplete_response(output=partial), function_response(), text_response())
        self.assertTrue(assistant.ask("How did player 10 score?")["sources"])
        self.assertEqual(model.requests[0]["input"], model.requests[1]["input"])

    def test_repeated_truncation_reports_token_limit_not_missing_data(self):
        assistant, model = self.scripted_assistant(incomplete_response(), incomplete_response())
        with self.assertRaisesRegex(RuntimeError, "response token limit"):
            assistant.ask("How is J.Garner doing?")
        self.assertEqual(len(model.requests), 2)

    def test_other_incomplete_response_is_not_retried_or_returned(self):
        assistant, model = self.scripted_assistant(
            incomplete_response(reason="content_filter", answer="partial answer"))
        with self.assertRaisesRegex(RuntimeError, "content_filter"):
            assistant.ask("How did player 10 score?")
        self.assertEqual(len(model.requests), 1)

    def test_empty_completed_response_does_not_claim_no_data(self):
        assistant, _ = self.scripted_assistant(text_response(""))
        with self.assertRaisesRegex(RuntimeError, "empty answer"):
            assistant.ask("How did player 10 score?")

    def test_genuine_empty_lookup_returns_coverage_guidance(self):
        repository = Mock()
        repository.search_players.return_value = []
        assistant, _ = self.scripted_assistant(
            function_response("search_players", '{"name":"Nobody","limit":10}'),
            text_response("No match."), repository=repository)
        result = assistant.ask("How did Nobody score?")
        self.assertEqual(result["sources"], [])
        self.assertIn("surname", result["answer"])

    def test_named_comparison_can_finish_after_four_sequential_lookups(self):
        assistant, model = self.scripted_assistant(
            function_response("search_players", '{"name":"Garner","limit":10}', "one"),
            function_response(call_id="two"),
            function_response("search_players", '{"name":"Lavia","limit":10}', "three"),
            function_response(call_id="four"), text_response())
        self.assertTrue(assistant.ask("Compare Garner with Lavia")["answer"])
        self.assertEqual(len(model.requests), 5)

    def test_six_sequential_lookups_leave_room_for_final_answer(self):
        calls = [function_response(call_id=str(index)) for index in range(MAX_TOOL_CALLS)]
        assistant, model = self.scripted_assistant(*calls, text_response())
        self.assertTrue(assistant.ask("Compare these player seasons")["sources"])
        self.assertEqual(model.requests[-1]["tool_choice"], "none")

    def test_more_than_six_tool_calls_are_rejected(self):
        calls = [function_response(call_id=str(index)).output[0]
                 for index in range(MAX_TOOL_CALLS + 1)]
        assistant, _ = self.scripted_assistant(SimpleNamespace(output=calls, output_text=""))
        with self.assertRaisesRegex(RuntimeError, "lookup limit"):
            assistant.ask("Compare these player seasons")

    def test_bad_marker_gets_one_correction_and_the_reason_is_logged(self):
        assistant, model = self.scripted_assistant(
            function_response(), text_response("Nine did well: {9:39:2025 goals_per_90}."),
            text_response("Ten: {10:39:2025 goals_per_90}."))
        with self.assertLogs("scout_backend", level="WARNING") as logs:
            result = assistant.ask("How did player 10 score?")

        self.assertTrue(result["answer"].startswith("Ten: 0.57.\n\n**Position not recorded**"))
        self.assertTrue(result["answer"].endswith("\n\nSources: [10:39:2025]"))
        self.assertEqual(len(model.requests), 3)
        correction = model.requests[2]["input"][-1]["content"]
        self.assertIn("{9:39:2025 goals_per_90}", correction)
        self.assertIn("10:39:2025", correction)
        self.assertIn("Nine did well", logs.output[0])

    def test_markers_are_filled_from_their_own_row(self):
        sources = {
            "7:39:2024": {"player_id": 7, "league_id": 39, "season": 2024, "minutes": 753,
                          "passes_attempted": 330, "pass_accuracy_pct": 85.2,
                          "tackles_per_90": 3.2, "tackles_per_90_percentile": 97,
                          "dribble_success_pct": None, "team_names": ["AFC Bournemouth"]},
            "8:39:2024": {"player_id": 8, "league_id": 39, "season": 2024, "minutes": 1595,
                          "passes_attempted": 696, "pass_accuracy_pct": 82.0},
        }
        filled, used, unknown = fill_markers(
            "Scott ({7:39:2024 team_names}) made {7:39:2024 passes_attempted} passes at "
            "{7 : 39 : 2024.pass_accuracy_pct} in {7:39:2024 minutes} minutes, with "
            "{7:39:2024 tackles_per_90} tackles per 90 ({7:39:2024 tackles_per_90_percentile}) "
            "and dribbling {7:39:2024 dribble_success_pct}. Garner made "
            "{8:39:2024 passes_attempted} at {8:39:2024, pass_accuracy_pct}.", sources)
        self.assertEqual(filled, (
            "Scott (AFC Bournemouth) made 330 passes at 85.2% in 753 minutes, with "
            "3.20 tackles per 90 (97th percentile (high)) and dribbling not available. "
            "Garner made 696 at 82.0%."))
        self.assertEqual(used, ["7:39:2024", "8:39:2024"])
        self.assertEqual(unknown, [])

    def test_markers_for_missing_rows_fields_or_in_unreadable_forms_are_reported(self):
        sources = {"7:39:2024": {"player_id": 7, "league_id": 39, "season": 2024, "minutes": 753}}
        filled, used, unknown = fill_markers(
            "{9:39:2024 minutes} {7:39:2024 wages} {Scott 2024 minutes} {7:39:2024 minutes}", sources)
        self.assertEqual(unknown, ["{9:39:2024 minutes}", "{7:39:2024 wages}", "{Scott 2024 minutes}"])
        self.assertEqual(used, ["7:39:2024"])
        self.assertTrue(filled.endswith(" 753"))

    def test_figures_table_shows_role_statistics_with_percentiles_by_position(self):
        scott = {"player_id": 7, "player_name": "Alex Scott", "season": 2024, "minutes": 753,
                 "detailed_position": "Central Midfield", "percentile_pool_min_minutes": 1140,
                 "key_passes_per_90": 1.43, "key_passes_per_90_percentile": 77,
                 "pass_accuracy_pct": 85.2, "pass_accuracy_pct_percentile": 51,
                 "passes_per_90": 39.44, "passes_per_90_percentile": 38,
                 "duel_win_pct": None, "duel_win_pct_percentile": None, "average_rating": 6.88}
        garner = {"player_id": 8, "player_name": "James Garner", "season": 2025, "minutes": 3414,
                  "detailed_position": "Defensive Midfield", "percentile_pool_min_minutes": 1140,
                  "role_score": 81.3, "duel_win_pct": 61.3, "duel_win_pct_percentile": 90}
        table = figures_table([scott, garner])
        central, defensive, note = table.split("\n\n**")[0], table.split("\n\n**")[1], table
        self.assertTrue(central.startswith("**Central Midfield**\n\n| Player, season | Minutes | "
                                           "Key passes /90 | Final-third passes /90 | Passes /90 |"))
        self.assertIn("| Alex Scott, 2024/25 | 753† | 1.43 (77th) | – | 39.44 (38th) | "
                      "85.2% (51st) |", central)
        self.assertTrue(central.rstrip().endswith("| – | 6.88 |"))
        self.assertIn("Defensive Midfield**\n\n| Player, season | Minutes | Role score | ", defensive)
        self.assertIn("| James Garner, 2025/26 | 3,414 | 81.3 | ", defensive)
        self.assertIn("61.3% (90th)", defensive)
        self.assertIn("† Too few minutes", note)
        self.assertNotIn("†", figures_table([garner]))
        # Each player's seasons run newest first, whatever order the answer used them in.
        ordered = figures_table([scott, garner, {**scott, "season": 2025}])
        self.assertLess(ordered.index("Alex Scott, 2025/26"), ordered.index("Alex Scott, 2024/25"))

    def test_values_read_naturally(self):
        for field, value, expected in (
                ("minutes", 2863, "2,863"), ("season", 2025, "2025"), ("goals_per_90", 0.2, "0.20"),
                ("role_score", 78.4, "78.4"), ("average_team_possession_pct", 50.0, "50.0%"),
                ("x_percentile", 1, "1st percentile (low)"),
                ("x_percentile", 12, "12th percentile (low)"),
                ("x_percentile", 35, "35th percentile (below average)"),
                ("x_percentile", 53, "53rd percentile (average)"),
                ("x_percentile", 60, "60th percentile (above average)"),
                ("x_percentile", 80, "80th percentile (high)"),
                ("x_percentile", 100, "100th percentile (high)")):
            with self.subTest(field=field, value=value):
                self.assertEqual(show_value(field, value), expected)

    def test_typed_statistics_are_found_and_other_numbers_pass(self):
        sources = {"7:39:2025": {"player_id": 7, "league_id": 39, "season": 2025}}
        for text in ("In 2025/26 (league 39, player 7) he ranked well per 90.",
                     "1. He is one of 3 players, in a team in the mid-40s for possession.",
                     "Among players under 23 with 1500 minutes, over 90 minutes."):
            with self.subTest(text=text):
                self.assertEqual(typed_figures(text, sources, [23.0, 1500.0]), [])
        self.assertEqual(
            typed_figures("He made 696 passes at 82.0%, 51st percentile, in 2,863 minutes.",
                          sources, []),
            ["696", "82.0%", "51", "2,863"])

    def test_typed_figure_gets_one_correction_then_a_visible_warning(self):
        typed = "Ten scored 0.75 per 90, or {10:39:2025 goals_per_90}."
        marked = "Ten scored {10:39:2025 goals_per_90} per 90."
        assistant, model = self.scripted_assistant(
            function_response(), text_response(typed), text_response(marked))
        with self.assertLogs("scout_backend", level="WARNING"):
            result = assistant.ask("How did player 10 score?")
        self.assertTrue(result["answer"].startswith("Ten scored 0.57 per 90.\n\n"))
        self.assertIn("| Player 10, 2025/26 |", result["answer"])
        self.assertEqual(result["unverified_figures"], [])
        self.assertIn("0.75", model.requests[2]["input"][-1]["content"])

        assistant, model = self.scripted_assistant(
            function_response(), text_response(typed), text_response(typed))
        with self.assertLogs("scout_backend", level="WARNING"):
            result = assistant.ask("How did player 10 score?")
        self.assertEqual(len(model.requests), 3)
        self.assertEqual(result["unverified_figures"], ["0.75"])
        self.assertTrue(result["answer"].startswith("Ten scored 0.75 per 90, or 0.57."))
        self.assertIn("Not verified", result["answer"])

    def test_answer_without_a_usable_marker_is_rejected_after_one_correction(self):
        for answer in ("Claim {99:39:2025 goals_per_90}.", "He scored a lot."):
            with self.subTest(answer=answer):
                assistant, model = self.scripted_assistant(
                    function_response(), text_response(answer), text_response(answer))
                with self.assertLogs("scout_backend", level="WARNING"):
                    with self.assertRaisesRegex(RuntimeError, "retrieved season rows"):
                        assistant.ask("How did player 10 score?")
                self.assertEqual(len(model.requests), 3)

    def test_follow_up_sends_earlier_turns_and_retrieves_again(self):
        responses = FakeResponses("Ten scored {10:39:2025 goals_per_90}, behind Nine.")
        assistant = ScoutAssistant(GoldRepository(lambda: FakeConnection([])),
                                   SimpleNamespace(responses=responses), "configured-model")
        previous = [{"role": "user", "content": "How did player 9 score?"},
                    {"role": "assistant", "content": "Nine scored 0.80 per 90.\n\nSources: [9:39:2025]"}]

        result = assistant.ask("And compared with player 10?", previous)

        self.assertEqual(responses.requests[0]["input"][:2], previous)
        self.assertEqual(responses.requests[0]["input"][2]["content"],
                         "And compared with player 10?")
        self.assertEqual([row["source_id"] for row in result["sources"]], ["10:39:2025"])


if __name__ == "__main__":
    unittest.main()
