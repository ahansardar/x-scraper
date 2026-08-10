import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = {
    ".env.example",
    "README.md",
    "docs/deployment_runbook.md",
    "tests/test_secret_hygiene.py",
}
PATTERNS = (
    re.compile(r"auth_token=[A-Za-z0-9_%.-]{12,}"),
    re.compile(r"ct0=[A-Za-z0-9_%.-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_%.-]{24,}"),
    re.compile(r"X_AUTH_TOKEN=\\S+"),
    re.compile(r"X_CT0=\\S+"),
    re.compile(r"X_BEARER=\\S+"),
)


def tracked_files():
    output = subprocess.check_output(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
    )
    return [ROOT / line.strip() for line in output.splitlines() if line.strip()]


class SecretHygieneTests(unittest.TestCase):
    def test_tracked_files_do_not_contain_raw_x_auth_material(self):
        offenders = []
        for path in tracked_files():
            rel = path.relative_to(ROOT).as_posix()
            if rel in ALLOWLIST or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern in PATTERNS:
                if pattern.search(text):
                    offenders.append(rel)
                    break

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
