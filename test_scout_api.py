"""HTTP contract checks without Databricks or OpenAI credentials."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import scout_api


class FakeRepository:
    def search_players(self, name, limit):
        return [{"player_id": 10, "player_name": name, "limit_seen": limit}]

    def player_seasons(self, player_id):
        return [{"player_id": player_id, "season": 2025}] if player_id == 10 else []

    def leaderboard(self, args):
        return [{"player_id": 10, "metric": args.metric,
                 "min_minutes": args.min_minutes}]


class FakeAssistant:
    def ask(self, question):
        return {"answer": question, "sources": []}


class ScoutApiTests(unittest.TestCase):
    def setUp(self):
        scout_api.app.dependency_overrides[scout_api.repository] = FakeRepository
        self.client = TestClient(scout_api.app)

    def tearDown(self):
        scout_api.app.dependency_overrides.clear()

    def test_public_data_routes_and_validation(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.assertIn("goals_per_90", self.client.get("/metrics").json()["ranking_metrics"])
        self.assertEqual(self.client.get("/players?name=Ten").json()["players"][0]["player_id"], 10)
        self.assertEqual(self.client.get("/players?name=%20%20%20").status_code, 422)
        self.assertEqual(self.client.get("/players/10/seasons").status_code, 200)
        self.assertEqual(self.client.get("/players/99/seasons").status_code, 404)
        self.assertEqual(self.client.get("/leaderboard?metric=bogus").status_code, 422)
        ranked = self.client.get("/leaderboard?metric=goals_per_90").json()["players"]
        self.assertEqual(ranked[0]["min_minutes"], 450)

    def test_question_requires_server_key(self):
        with patch.dict(os.environ, {"SCOUT_API_KEY": "private-token"}):
            body = {"question": "Compare these player seasons"}
            self.assertEqual(self.client.post("/scout/ask", json=body).status_code, 401)
            self.assertEqual(self.client.post("/scout/ask", json={"question": "        "},
                                              headers={"X-Scout-API-Key": "private-token"}).status_code, 422)
            self.assertEqual(self.client.post("/scout/ask", json=body,
                                               headers={"X-Scout-API-Key": "wrong"}).status_code, 401)
            with patch.object(scout_api, "assistant", return_value=FakeAssistant()):
                response = self.client.post("/scout/ask", json=body,
                                            headers={"X-Scout-API-Key": "private-token"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["answer"], body["question"])


if __name__ == "__main__":
    unittest.main()
