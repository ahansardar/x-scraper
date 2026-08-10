from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from xingestion.smoke import SmokeClient
from xrev.runtime import load_env_file


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env_file(ROOT / ".env")
    base_url = _arg(argv, "--base-url", "http://127.0.0.1:8000")
    query = _arg(argv, "--submit", None)
    wait_seconds = int(_arg(argv, "--wait", "60"))
    client = SmokeClient(base_url=base_url)
    result = client.run(submit_query=query, wait_seconds=wait_seconds)
    for message in result.messages:
        print(message)
    return 0 if result.ok else 1


def _arg(argv, name, default):
    if name not in argv:
        return default
    index = argv.index(name)
    if index + 1 >= len(argv):
        raise ValueError(f"{name} requires a value")
    return argv[index + 1]


if __name__ == "__main__":
    raise SystemExit(main())
