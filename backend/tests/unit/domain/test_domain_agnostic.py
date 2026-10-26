import re
from pathlib import Path

APP = Path(__file__).resolve().parents[3] / "app"
WORDS = re.compile(r"watch|fashion|interior|dial|sofa", re.IGNORECASE)


def test_engine_code_names_no_domain() -> None:
    files = [p for p in APP.rglob("*.py") if "lenses" not in p.relative_to(APP).parts]
    assert files
    offenders = [str(p) for p in files if WORDS.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
