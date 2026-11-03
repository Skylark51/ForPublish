"""Integration checks for the research workflow without external API access."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import app


SAMPLE = {
    "message": {"items": [
        {"DOI": "10.1000/example-1", "title": ["Iron nitrosyl mechanisms"],
         "published": {"date-parts": [[2024, 10]]}, "container-title": ["Example Journal"],
         "author": [{"given": "Ada", "family": "Lovelace"}],
         "abstract": "<jats:p>Mechanistic <b>work</b>.</jats:p>"},
        {"DOI": "10.1000/example-1", "title": ["Duplicate"]},
        {"DOI": "10.1000/example-2", "title": ["Ligand effects"],
         "issued": {"date-parts": [[2023]]}},
    ]}
}


class FakeResponse:
    def __init__(self, value):
        self.data = json.dumps(value).encode()
    def __enter__(self):
        import io
        return io.BytesIO(self.data)
    def __exit__(self, *_args):
        return None


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "research.db"
        app.initialize_database(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_crossref_normalization_and_search_filters(self):
        def response(req, timeout):
            params = parse_qs(urlsplit(req.full_url).query)
            self.assertEqual(params["rows"], ["15"])
            self.assertEqual(params["filter"], ["from-pub-date:2020-01-01,until-pub-date:2026-12-31"])
            self.assertEqual(timeout, 25)
            return FakeResponse(SAMPLE)
        with patch.object(app.urllib.request, "urlopen", side_effect=response):
            papers = app.fetch_crossref("iron nitrosyl", 15, 2020, 2026)
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0]["year"], 2024)
        self.assertEqual(papers[0]["authors"], "Ada Lovelace")
        self.assertEqual(papers[0]["abstract"], "Mechanistic work .")
        self.assertTrue(papers[0]["url"].startswith("https://doi.org/"))

    def test_persistence_and_key_not_saved(self):
        with patch.object(app, "fetch_crossref", return_value=[app.normalize_paper(SAMPLE["message"]["items"][0])]), \
             patch.object(app, "openai_analysis", return_value=("AI suggested a hypothesis", {"input_tokens": 5})):
            result = app.run_research({"query": "Fe nitrosyl mechanism", "api_key": "SECRET_KEY_DONT_STORE"}, self.db)
        self.assertEqual(result["id"], 1)
        self.assertEqual(len(result["ideas"]), 4)
        self.assertEqual(app.read_run(self.db, 1)["ai_analysis"], "AI suggested a hypothesis")
        self.assertEqual(app.list_runs(self.db)[0]["paper_count"], 1)
        self.assertNotIn("SECRET_KEY_DONT_STORE", self.db.read_bytes().decode("utf-8", errors="replace"))
        self.assertIn(b"Title,Year,Journal", app.export_csv(result))

    def test_validation(self):
        with self.assertRaises(ValueError):
            app.parse_options({"query": "no"})
        with self.assertRaises(ValueError):
            app.parse_options({"query": "Fe nitrosyl", "year_from": "2027", "year_to": "2020"})
        with self.assertRaises(ValueError):
            app.parse_options({"query": "Fe nitrosyl", "limit": "5000"})


if __name__ == "__main__":
    unittest.main()
