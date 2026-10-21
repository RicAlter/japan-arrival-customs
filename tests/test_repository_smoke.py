"""Repository-safe checks that require no business workbook or production state."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "workbuddy" / "japan-arrival-customs"


class RepositorySmokeTests(unittest.TestCase):
    def test_skill_source_and_entrypoint_exist(self):
        self.assertTrue((SKILL / "SKILL.md").is_file())
        self.assertTrue((SKILL / "requirements.txt").is_file())
        self.assertTrue((SKILL / "scripts" / "run.py").is_file())

    def test_data_directories_are_git_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in ("/inputs/", "/outputs/", "/reports/", "/历史数据/", "**/security/trusted_sessions.json"):
            self.assertIn(entry, ignore)

    def test_readme_states_no_business_data_policy(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("无业务数据", readme)
        self.assertIn("不会批准归类", readme)


if __name__ == "__main__":
    unittest.main()
