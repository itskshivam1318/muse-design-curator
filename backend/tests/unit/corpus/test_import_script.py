import importlib.util
import json
from pathlib import Path

import respx

from app.corpus.sources.commons import API

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "import_corpus.py"


def load():
    spec = importlib.util.spec_from_file_location("import_corpus_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@respx.mock
def test_import_appends_and_deduplicates_by_id(tmp_path: Path) -> None:
    respx.get(API).respond(json={"query": {"pages": [{
        "pageid": 5, "title": "File:A.jpg", "index": 1,
        "imageinfo": [{"url": "https://u/5.jpg", "descriptionurl": "https://c/5", "extmetadata": {"LicenseShortName": {"value": "CC0"}}}],
    }]}})  # fmt: skip
    mod = load()
    argv = [
        "--domain",
        "watch",
        "--source",
        "commons",
        "--query",
        "wristwatch dial",
        "--limit",
        "200",
        "--manifest-dir",
        str(tmp_path),
    ]
    assert mod.main(argv) == 0
    assert mod.main(argv) == 0
    lines = (tmp_path / "watch.jsonl").read_text().splitlines()
    assert [json.loads(ln)["id"] for ln in lines] == ["cx_commons_5"]
