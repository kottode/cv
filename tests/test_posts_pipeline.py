from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cvapp.config import AutoConfig, CVState
from cvapp.internal.posts_pipeline import fit_cached_posts, merge_fetched_posts


class PostsPipelineTests(unittest.TestCase):
    def test_merge_fetched_posts_preserves_existing_fit_fields(self) -> None:
        posts = [
            {
                "id": "abc",
                "url": "https://example.com/jobs/1",
                "company": "OldCo",
                "title": "Old Title",
                "status": "accepted",
                "fit_score": 88,
                "grade": "A",
                "matched_tags": ["react"],
                "missing_tags": ["aws"],
            }
        ]
        fetched = [
            {
                "url": "https://example.com/jobs/1",
                "company": "NewCo",
                "title": "New Title",
                "description": "Updated description",
                "source_site": "linkedin",
                "search_term": "frontend",
            },
            {
                "url": "https://example.com/jobs/2",
                "company": "Acme",
                "title": "Engineer",
                "description": "Second post",
                "source_site": "indeed",
                "search_term": "frontend",
            },
        ]

        summary = merge_fetched_posts(posts, fetched, source="jobspy")

        self.assertEqual(summary["added"], 1)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(len(posts), 2)
        updated = posts[0]
        self.assertEqual(updated["company"], "NewCo")
        self.assertEqual(updated["title"], "New Title")
        self.assertEqual(updated["fit_score"], 88)
        self.assertEqual(updated["status"], "accepted")

    def test_fit_cached_posts_reuses_resume_hash_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = CVState(current_job="frontend", current_name="resume", current_title="Frontend Engineer")
            config = AutoConfig(min_score=60)
            posts = [
                {
                    "id": "p1",
                    "url": "https://example.com/jobs/1",
                    "company": "Acme",
                    "title": "Frontend Engineer",
                    "description": "React TypeScript GraphQL",
                    "status": "fetched",
                    "apply_status": "not-attempted",
                }
            ]

            with patch("cvapp.internal.posts_pipeline.build_tags_from_resume", return_value=["react", "typescript"]):
                with patch(
                    "cvapp.internal.posts_pipeline.analyze_job_fit",
                    return_value={
                        "score": 82,
                        "grade": "B",
                        "job_tags": ["react"],
                        "matched_tags": ["react"],
                        "missing_tags": ["graphql"],
                    },
                ):
                    with patch("cvapp.internal.posts_pipeline.keyword_filter_reason", return_value=""):
                        first = fit_cached_posts(root, state, config, posts, force=False)

            self.assertEqual(first["scored"], 1)
            self.assertEqual(first["cached"], 0)
            self.assertEqual(len(first["accepted"]), 1)
            self.assertTrue(posts[0].get("fit_resume_hash"))

            with patch(
                "cvapp.internal.posts_pipeline.analyze_job_fit",
                side_effect=AssertionError("analyze_job_fit should not run for cached rows"),
            ):
                second = fit_cached_posts(root, state, config, posts, force=False)

            self.assertEqual(second["scored"], 0)
            self.assertEqual(second["cached"], 1)
            self.assertEqual(len(second["accepted"]), 1)


if __name__ == "__main__":
    unittest.main()
