import json
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import settings
from app.tasks import ai_analysis


class TestRepoMetadataExtraction(unittest.TestCase):
    def test_extract_repo_metadata_with_branch_and_commit(self):
        record = SimpleNamespace(
            metadata_json=json.dumps(
                {
                    "extra_fields": {
                        "metadata_json": {
                            "git_context": {
                                "repository_url": "https://git.example.com/org/repo.git",
                                "branch_name": "refs/heads/release/v2.3.1",
                                "commit_id": "a1b2c3d4e5f6",
                            }
                        }
                    }
                },
                ensure_ascii=False,
            )
        )

        repo_url, commit_id, branch_name, info = ai_analysis._extract_repo_metadata(record)

        self.assertEqual(repo_url, "https://git.example.com/org/repo.git")
        self.assertEqual(commit_id, "a1b2c3d4e5f6")
        self.assertEqual(branch_name, "release/v2.3.1")
        self.assertIn("branch_source", info)
        self.assertTrue(info["branch_source"].endswith("branch_name"))

    def test_normalize_branch_name(self):
        self.assertEqual(ai_analysis._normalize_branch_name("refs/heads/feature/perf"), "feature/perf")
        self.assertEqual(ai_analysis._normalize_branch_name("origin/hotfix/v1"), "hotfix/v1")
        self.assertIsNone(ai_analysis._normalize_branch_name("HEAD"))
        self.assertIsNone(ai_analysis._normalize_branch_name("deadbeef"))
        self.assertIsNone(ai_analysis._normalize_branch_name("feature has space"))


class TestCloneRepository(unittest.TestCase):
    def test_clone_repository_honors_branch_commit_and_token(self):
        temp_root = tempfile.mkdtemp(prefix="ai-analysis-clone-test-")
        fake_workspace = os.path.join(temp_root, "workspace")
        os.makedirs(fake_workspace, exist_ok=True)
        commands = []

        def _fake_run(cmd, capture_output, text, timeout):
            commands.append(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        old_token = settings.code_repo_git_token
        settings.code_repo_git_token = "test-token-123"
        try:
            with patch("app.tasks.ai_analysis.tempfile.mkdtemp", return_value=fake_workspace):
                with patch("app.tasks.ai_analysis.subprocess.run", side_effect=_fake_run):
                    ws = ai_analysis._clone_repository(
                        "https://git.example.com/org/private-repo.git",
                        commit_id="1234abcd",
                        branch_name="refs/heads/release/v9",
                    )
        finally:
            settings.code_repo_git_token = old_token
            shutil.rmtree(temp_root, ignore_errors=True)

        self.assertEqual(ws, fake_workspace)
        self.assertGreaterEqual(len(commands), 2)

        clone_cmd = commands[0]
        self.assertIn("--single-branch", clone_cmd)
        self.assertIn("--branch", clone_cmd)
        self.assertIn("release/v9", clone_cmd)
        self.assertTrue(any("oauth2:test-token-123@" in str(part) for part in clone_cmd))

        checkout_cmd = commands[1]
        self.assertEqual(checkout_cmd[:4], ["git", "-C", fake_workspace, "checkout"])
        self.assertEqual(checkout_cmd[-1], "1234abcd")


if __name__ == "__main__":
    unittest.main()
