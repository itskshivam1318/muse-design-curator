# Plugins

A plugin is a small tool you place on a board as a **node**. You connect items to it (images,
notes, videos, links), set its params, and press **Run**. The run happens in the background; what
it returns is written back onto the board: new images and notes appear in a column to the right
of the node, attributes land on the input items, and text or a table is shown in the node.

> **Trust warning.** A plugin runs on your machine with your permissions. The python runner
> starts it in a separate process with a stripped environment and a temporary working folder, but
> that is isolation from the app, **not a sandbox**: plugin code can read and write your files and
> reach the network. Only install plugins you have read or wrote yourself. User plugins are
> **never loaded in demo mode** (`DEMO_MODE=1`).

## Where plugins live

Built-in plugins ship in `backend/app/plugins/builtin/<id>/`. Your own plugins go in
`PLUGINS_DIR` (default `data/plugins`, relative to the repo root; gitignored), one folder each:

```
data/plugins/
  word-count/
    plugin.json     the manifest
    main.py         python runner: the entry file (plus any helper modules)
  tagline/
    plugin.json
    prompt.md       llm runner: the prompt template
```

Plugins are discovered at startup. After adding or editing one, reload without restarting:

```sh
curl -X POST http://localhost:8000/api/plugins/reload
# {"loaded": ["critique", "image", ..., "word-count"], "skipped": [{"folder": "x", "reason": "..."}]}
```

A folder with an invalid manifest is skipped and listed with the reason. Ids are unique, and a
user plugin cannot shadow a built-in. Then add the plugin to a board from the Plugins panel.

Two working examples are in [`docs/plugins/examples/`](plugins/examples/): `word-count` (python)
and `tagline` (llm). Copy a folder into `data/plugins/` and reload to try one.

## The manifest (`plugin.json`)

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Lowercase id, `^[a-z][a-z0-9_-]{1,31}$`. Unique across all plugins. |
| `name` | yes | Shown on the node card. |
| `description` | yes | One line; also the tool description agents see. |
| `mark` | yes | 1-4 characters shown as the node's badge (e.g. `PAL`). |
| `tint`, `ink` | yes | Badge background and text colours (CSS colours). |
| `runner` | yes | `python` or `llm` (`model` is for built-ins only). |
| `runs_on` | yes | A short "runs on" line for the card (e.g. `Python`, `Muse Spark`). Stored on generated images as their model. |
| `inputs` | yes | `{"kinds": [...], "min": 1, "max": 12}`. Kinds are `image`, `video`, `note`, `link`. |
| `params` | no | A JSON Schema object for the node's params. The card renders `string`, `enum`, `integer` and `boolean` (others get a JSON box); `default`, `enum`, `minimum`, `maximum` and `required` are checked. |
| `outputs` | yes | Any of `images`, `notes`, `attributes`, `text`, `table`. A run may only return what is declared. |
| `requires` | no | Setting names that must be set (e.g. `["VIDEO_MODEL"]`); otherwise the plugin shows as "not connected" and cannot run. |
| `entry` | python | The python file with `run(...)`, relative to the folder. |
| `prompt` | llm | The prompt template file, relative to the folder. |
| `output_schema` | llm | JSON Schema of the model's answer. |
| `output_map` | llm | Maps an output kind to a key of the answer, e.g. `{"notes": "taglines", "text": "why"}`. |

Unknown top-level keys are ignored.

## Python plugins

The entry file defines one function:

```python
def run(inputs, params, ctx):
    return {"notes": [{"text": "..."}]}
```

- `inputs`: a list of `{id, kind, label, attributes, note_text, image_path}`. `attributes` is
  `{key: value}` of the item's current attributes; `note_text` is set for notes; `image_path` is a
  read-only PNG copy of an image (or a video's chosen frame), otherwise `null`.
- `params`: the node's params with manifest defaults filled in.
- `ctx`: `{"board": {"title", "context", "notes"}}`; `notes` are the board's note texts, newest
  first.

Under the hood the app runs `python -I shim.py <plugin folder>`: the request goes in as JSON on
stdin and your return value comes back as JSON on stdout (the shim handles both; `print` output is
sent to stderr so it cannot corrupt the result). The process gets a fresh temporary folder as its
working directory and `HOME`, and only `PATH` and `PYTHONHASHSEED` in its environment. Limits: 30 s
(setting `PLUGIN_TIMEOUT_S`), 1 MB of output. When it fails, the last 4 KB of stderr become the
run's error message.

**Dependencies.** Plugins run under the app's own Python interpreter, so the standard library and
the packages installed with the backend (numpy, Pillow, scikit-image, scikit-learn, ...) are
importable. A plugin cannot add its own dependencies.

**Helper modules.** The plugin folder is put first on `sys.path`, so `main.py` can
`import my_helpers` from the same folder. Because it comes first, a helper named like a standard
library module (`json.py`, `random.py`, `types.py`) **shadows** that module for the whole run; give
helpers distinct names.

An image can be returned as base64 (`{"data_b64": ..., "caption": ...}`) or as a file the plugin
wrote inside its working folder (`{"path": "out.png", "caption": ...}`).

## LLM plugins

The `prompt` file is a template sent to the reasoning model together with the input images (up to
the provider's limit). Placeholders:

| Placeholder | Replaced with |
|---|---|
| `{{notes}}` | The connected notes' text, then the board's notes, one per line. |
| `{{board.title}}` | The board title. |
| `{{board.context}}` | The board brief (empty if none). |
| `{{params.<name>}}` | A param value (empty if unset). |

The model answers in the shape of `output_schema`. `output_map` then picks the outputs out of the
answer: each entry maps an output kind to a top-level key of the answer. For `notes`, a list of
strings or of `{text}` objects becomes one note each (an object's `verdict` or `label`, when
present, is put in front: `"fits: ..."`). Without `output_map` the answer must already be keyed by
output kinds.

**Strict mode.** The schema is sent in strict structured-output mode: every key of every object is
made **required** and every object is **closed** (`additionalProperties: false`), even if your
schema leaves them open. So there are no optional fields; declare a field the model may leave out
as nullable, e.g. `{"type": ["string", "null"]}`, and a `null` output is simply skipped.

## Outputs

A run returns (python) or maps to (llm) a dict with any of the declared kinds:

```json
{
  "images": [{"data_b64": "<base64 PNG/JPEG>", "caption": "..."}],
  "notes": [{"text": "..."}],
  "attributes": [{"item_id": "item_...", "key": "palette", "value": "#e6d7b4, #d9a85c",
                  "label": "Palette", "confidence": 0.9}],
  "text": "Shown in the node.",
  "table": {"columns": ["name", "count"], "rows": [["oak", 3]]}
}
```

- **images** become generated items (lineage back to the first image input), **notes** become
  notes; both are placed in a column to the right of the node.
- **attributes** are written onto input items (`item_id` must be one of the inputs). Values are
  text, numbers, booleans or a list (stored as text, comma-separated). They are stored with
  source `plugin`; confidence defaults to 1.0 for python and 0.7 for llm. A plugin never
  overwrites a value the user edited or confirmed; such writes are skipped and listed in the run's
  `skipped_attributes`. Re-parsing an item keeps plugin values.
- **text** and **table** are kept on the run and shown in the node.

Anything else, or a kind the manifest does not declare, fails the run with `PLUGIN_BAD_OUTPUT`.

## Runs and errors

`POST /api/nodes/{id}/run` queues a run (`202`, the run); `GET /api/plugin-runs/{run_id}` reads
it. The board's event stream carries `plugin_run.queued`, `plugin_run.progress`,
`plugin_run.done` and `plugin_run.failed`. A failed run has an `error_code`:

| Code | Meaning |
|---|---|
| `PLUGIN_BAD_INPUT` | Wrong input kinds or count, bad params, or inputs removed below `min`. |
| `PLUGIN_BAD_OUTPUT` | The result is not JSON or does not match the outputs. |
| `PLUGIN_TIMEOUT` | Ran longer than `PLUGIN_TIMEOUT_S`. |
| `PLUGIN_CRASHED` | The plugin raised or exited non-zero (stderr tail in the message). |
| `PLUGIN_MODEL_FAILED` | The model call failed. |
| `PLUGIN_NOT_CONNECTED` | A required setting is missing. |
| `PLUGIN_INTERRUPTED` | The app restarted while the run was in progress. |
