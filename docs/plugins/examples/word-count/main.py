"""Word count: an example python plugin (see docs/plugins.md).

`run` gets the connected items, the node's params (defaults filled in) and the board, and
returns a dict of outputs. Only the standard library and the app's own packages are importable.
"""


def _words(text):
    return len((text or "").split())


def run(inputs, params, ctx):
    counts = [(item["id"], _words(item["note_text"])) for item in inputs]
    total = sum(n for _, n in counts)
    out = {"notes": [{"text": f"{total} words"}]}
    if params.get("per_note"):
        out["text"] = "\n".join(f"{item_id}: {n}" for item_id, n in counts)
    return out
