"""Runs one python plugin: `python -I shim.py <plugin_dir>`, request JSON on stdin, result JSON on
stdout. Standalone on purpose (stdlib only, no `app` imports): it runs in a fresh interpreter."""

import importlib.util
import json
import sys
from pathlib import Path


def main() -> int:
    folder = Path(sys.argv[1]).resolve()
    manifest = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
    request = json.loads(sys.stdin.read())
    sys.path.insert(0, str(folder))  # the plugin may import its own helper modules
    spec = importlib.util.spec_from_file_location("plugin_main", folder / manifest["entry"])
    if spec is None or spec.loader is None:
        print(f"cannot load {manifest['entry']}", file=sys.stderr)
        return 2
    module = importlib.util.module_from_spec(spec)
    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # stray prints from the plugin must not corrupt the result
    try:
        spec.loader.exec_module(module)
        result = module.run(request["inputs"], request["params"], {"board": request["board"]})
    finally:
        sys.stdout = real_stdout
    try:
        text = json.dumps(result)
    except (TypeError, ValueError) as e:
        print(f"result is not JSON: {e}", file=sys.stderr)
        return 3
    real_stdout.write(text)
    real_stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
