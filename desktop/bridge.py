import json
import subprocess
import sys
from pathlib import Path

# In source this file is under desktop/. The packager puts it next to repo_bugbot/.
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here if (here / "repo_bugbot").is_dir() else here.parent))
from repo_bugbot.desktop_api import dispatch

try:
    request = json.load(sys.stdin)
    response = {"value": dispatch(sys.argv[1], request)}
except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
    response = {"error": str(exc)[:700]}
print(json.dumps(response, ensure_ascii=True))
