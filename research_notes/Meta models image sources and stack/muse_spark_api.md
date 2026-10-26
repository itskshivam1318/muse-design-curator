# Meta Model API: Muse Spark 1.3 (and siblings) developer interface, as of 26 Oct 2026

Method note: dev.meta.ai docs serve raw Markdown when `.md` is appended to a docs URL (e.g. `https://dev.meta.ai/docs/quickstart.md`). Quotes below come verbatim from those Markdown files, fetched 2026-10-26. The `.md` form of the Geographic Use Policy returned a 404 page, so that section relies on a WebFetch of the HTML page, which returns summaries plus short verbatim excerpts only. The Cerebral Valley page renders client-side, so its text was pulled from the JSON embedded in the raw HTML. The Credit Terms PDF linked from that page was downloaded and read in full.

## Q1. Base URL, auth, OpenAI compatibility, SDKs

### Takeaway
The base URL is `https://api.meta.ai/v1` and auth is a Bearer token (keys start with `LLM_`). The API is drop-in compatible with OpenAI Responses and Chat Completions, and with the Anthropic Messages API. Meta ships no SDK of its own for text models: use `openai` (pip/npm) and pass the base URL and key explicitly.

### Cited Findings
- Base URL: "Most tools ask for three values: the base URL `https://api.meta.ai/v1`, your `MODEL_API_KEY`, and the model ID `muse-spark-1.3`." — [Quickstart](https://dev.meta.ai/docs/quickstart)
- Compatibility: "Model API is drop-in compatible with the OpenAI SDK, the Anthropic SDK, and OpenAI-compatible agent CLIs, so most stacks work with a base-URL and key change." — [Quickstart](https://dev.meta.ai/docs/quickstart)
- Auth header: "Pass the key as a Bearer token in the `Authorization` header". Key format: "API keys start with `LLM_`, followed by a numeric ID and the secret, separated by underscores: `LLM_1607358788850350_nx9.....LJY`". Keys come from the dashboard: **API keys** → **Create API key**, and the key is shown once. — [Authentication](https://dev.meta.ai/docs/authentication)
- Verbatim auth curl:
  ```shell
  curl https://api.meta.ai/v1/chat/completions \
    -H "Authorization: Bearer $MODEL_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "muse-spark-1.3",
      "messages": [{"role": "user", "content": "Hello"}]
    }'
  ```
  — [Authentication](https://dev.meta.ai/docs/authentication)
- Keys belong to a team and share its rate limits: "Keys on the same team share rate limits." Also: "Keep keys out of client code: mobile and browser code is visible to users. Proxy requests through a server you control." — [Authentication](https://dev.meta.ai/docs/authentication)
- No first-party client: "Meta Model API doesn't need a client of its own." Install `pip install openai` / `npm install openai`. The Anthropic SDK also works, with `base_url="https://api.meta.ai"` and the key passed as `auth_token` (the SDK appends `/v1/messages`). Also listed: LangChain, LlamaIndex, Vercel AI SDK, LiteLLM (`model="openai/muse-spark-1.3"`, `api_base="https://api.meta.ai/v1"`). — [SDKs and libraries](https://dev.meta.ai/docs/sdks)
- Gotcha: "The OpenAI SDK doesn't auto-read `MODEL_API_KEY`. Always pass `api_key` explicitly or set `OPENAI_API_KEY` to your Model API key." — [Quickstart](https://dev.meta.ai/docs/quickstart)
- Endpoints in the docs: `POST /v1/responses` (plus retrieve, delete, cancel, and `POST /v1/responses/input_tokens`), `POST /v1/chat/completions`, Messages (`/v1/messages`), Files (`/v1/files`), `GET /v1/models`, `GET /v1/models/{model}`, `/v1/images/generations`, `/v1/images/edits`, `POST /v1/asr/transcribe`, `wss://api.meta.ai/v1/asr/realtime`. — [Models](https://dev.meta.ai/docs/models), [llms.txt index](https://dev.meta.ai/llms.txt)
- Responses API is the recommended surface. Per the docs it is "the only endpoint that carries the model's chain of thought between calls", and search grounding is available only there. — [Responses API](https://dev.meta.ai/docs/protocols/responses), [Chat completion](https://dev.meta.ai/docs/protocols/chat-completions)
- Verbatim TypeScript first call:
  ```typescript
  import OpenAI from 'openai';
  const apiKey = process.env.MODEL_API_KEY;
  if (!apiKey) {
    throw new Error('MODEL_API_KEY is not set');
  }
  const client = new OpenAI({
    baseURL: 'https://api.meta.ai/v1',
    apiKey,
  });
  const response = await client.responses.create({
    model: 'muse-spark-1.3',
    input: 'What is the capital of France?',
  });
  ```
  — [Quickstart](https://dev.meta.ai/docs/quickstart)
- Verbatim Responses response shape. Reasoning tokens count toward `output_tokens`:
  ```json
  {
    "id": "resp_abc123",
    "object": "response",
    "created_at": 1792177394,
    "status": "completed",
    "model": "muse-spark-1.3",
    "reasoning": { "effort": "high" },
    "output": [
      { "id": "rs_abc123", "type": "reasoning", "summary": [], "status": "completed" },
      { "id": "msg_abc123", "type": "message", "role": "assistant", "status": "completed",
        "content": [ { "type": "output_text", "text": "The capital of France is **Paris**.", "annotations": [] } ] }
    ],
    "usage": { "input_tokens": 15, "input_tokens_details": { "cached_tokens": 0 },
      "output_tokens": 258, "output_tokens_details": { "reasoning_tokens": 241 }, "total_tokens": 273 }
  }
  ```
  (Whitespace compacted; keys and values are verbatim.) — [Quickstart](https://dev.meta.ai/docs/quickstart)
- Verbatim Chat Completions response shape:
  ```json
  {
    "id": "chatcmpl-abc123",
    "object": "chat.completion",
    "created": 1714502400,
    "model": "muse-spark-1.3",
    "choices": [ { "index": 0, "message": { "role": "assistant", "content": "Here are three key differences between TCP and UDP..." }, "finish_reason": "stop" } ],
    "usage": { "prompt_tokens": 25, "completion_tokens": 19, "total_tokens": 44 }
  }
  ```
  — [Chat completion](https://dev.meta.ai/docs/protocols/chat-completions)
- Roles: `developer` is the highest-precedence instruction role. `system` is "accepted for OpenAI compatibility and treated at the same level as `developer`". — [Chat completion](https://dev.meta.ai/docs/protocols/chat-completions)

### Inferences
- For a Node/Next.js app: `npm install openai`, `new OpenAI({ baseURL: 'https://api.meta.ai/v1', apiKey: process.env.MODEL_API_KEY })`, and call it from a server route only. The Vercel AI SDK with `@ai-sdk/openai` (which uses the Responses API) is the documented adapter if you want streaming UI helpers.

### Gaps
- There is no official Meta-branded Python/TS package for text models. The only Meta npm/PyPI packages found are the SAM parsers (`@meta-sam/parser`, `meta_sam_parser`). I did not check Meta's GitHub org separately.

## Q2. Model IDs, context, image/video/PDF input limits

### Takeaway
Use `muse-spark-1.3` (Standard) or `muse-spark-1.3-contributor` (cheap, but your content may be used for training). Siblings are `muse-wonder-1.0` (premium, preview), `muse-spark-1.2`, and `muse-spark-1.1`. All have a 1,048,576-token context and accept text, image, video (MP4), audio, and PDF. Image limits per request are 50 images, 50 MB per image inline (1 GiB via the Files API), and JPEG/PNG/GIF/WebP/ICO. Images can be sent as a URL, a base64 data URL, or a `file_id`.

### Cited Findings
- Model table: `muse-wonder-1.0`, `muse-spark-1.3`, `muse-spark-1.3-contributor`, `muse-spark-1.2`, `muse-spark-1.2-contributor`, `muse-spark-1.1`, plus `muse-image-1.0` (image output), `muse-voice-transcribe-1.0`, `sam-3.1`. The open-weight models are Muse Spark Open and Muse Glimmer. — [Models](https://dev.meta.ai/docs/models)
- "Muse Spark comes in three versions. All take text, image, video, audio, and PDF input, return text, and have a 1,048,576-token context window." Muse Spark 1.3 is "the latest version, tuned for agentic workflows ... **Recommended for new work.**" — [Models](https://dev.meta.ai/docs/models)
- Max output: the documented OpenCode config sets `"limit": { "context": 1048576, "output": 131072 }` for `muse-spark-1.3`. — [Quickstart](https://dev.meta.ai/docs/quickstart)
- Audio caveat: "Audio understanding in Muse Spark 1.3 is not fully supported, and response quality for requests that include audio may be degraded." — [Models](https://dev.meta.ai/docs/models)
- Muse Wonder: "Muse Wonder is in preview." It is available on Model API in Standard mode only. "Muse Wonder and Muse Wonder Full aren't currently available in South Korea". Muse Wonder Full is available only in Muse Code subscriptions. "Muse Wonder and Muse Spark take the same requests on the same endpoints, so moving a workload between them is a model ID change." — [Models](https://dev.meta.ai/docs/models)
- Three ways to send an image: "**Public URL** — a fully qualified `http`/`https` image link. **Base64 data URL** — the image bytes inline, no hosting required. **Uploaded file** — a `file_id` from the Files API." Also: "Only include images in `user`-role messages." — [Image understanding](https://dev.meta.ai/docs/image-understanding)
- Verbatim Responses image block: `{"type": "input_image", "image_url": "https://upload.wikimedia.org/.../1280px-Avocado_Hass_-_single_and_halved.jpg"}` sits inside `{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "What is in this image?"}, ...]}`. Base64 form: "pass a base64 `data:` URL as the same `image_url` string (for example, `\"data:image/jpeg;base64,<encoded bytes>\"`)". File form: `{"type": "input_image", "file_id": file.id}` or `{"type": "input_file", "file_id": file.id}`. Server-fetched URL form: `{"type": "input_file", "file_url": "https://example.com/photo.png"}`. — [Image understanding](https://dev.meta.ai/docs/image-understanding)
- Verbatim Chat Completions image block: `{"type": "image_url", "image_url": {"url": "https://..."}}` placed after `{"type": "text", "text": "Describe what you see in this image."}`. "Chat Completions wraps the image in an `image_url` **object** ... rather than the plain string the Responses API uses." — [Image understanding](https://dev.meta.ai/docs/image-understanding)
- Limits table (verbatim values): "Max file size per image (inline `image_url`) | 50 MB (50,000,000 bytes)"; "Max file size per image (`input_file` via Files API) | 1 GiB"; "Max images per request | **50**, enforced. More than 50 returns `HTTP 400`."; "PDF page-images retained | First 50 per PDF"; "Supported MIME types | `image/jpeg`, `image/jpg`, `image/png`, `image/gif`, `image/webp`, `image/x-icon`". Error text: `request contains <n> images, exceeding the maximum of 50 allowed per request`. — [Image understanding](https://dev.meta.ai/docs/image-understanding)
- Undecodable images fail with "`HTTP 400` (`type: invalid_request_error`, `code: null`)". — [Image understanding](https://dev.meta.ai/docs/image-understanding)
- Image token cost: "a 1x1 image ≈ 3 tokens"; "a ~1280px image adds roughly **1,300–1,500 tokens**"; fixed overhead "~110 input tokens". For exact counts, use `POST /v1/responses/input_tokens`. The docs do not document a detail/resolution parameter. — [Image understanding](https://dev.meta.ai/docs/image-understanding)
- Grounding: boxes and points come back on a "normalized **0–1000** grid", where `(0,0)` is top-left. "The model may emit a value slightly outside the range (for example `1001`) ... so clamp to the image bounds." — [Image understanding](https://dev.meta.ai/docs/image-understanding)
- File types: video `video/mp4` only. Audio is `audio/mpeg` and `audio/wav`. PDF: text from the "first 100 pages", images from the "first 50 page-images". Inline (`file_data` base64 or `file_url`) is capped at 50 MB, Files API upload at 1 GiB. Team storage is 100 GiB, and "Uploaded files don't expire". — [File handling](https://dev.meta.ai/docs/file-handling)
- Video tip: "set `max_tokens` (or `max_output_tokens`) to at least `4000`, or a transcript can come back empty with `finish_reason: length`." — [Video understanding](https://dev.meta.ai/docs/video-understanding)

### Inferences
- For a design-reference app, send thumbnails around 1024–1280px. Each costs about 1.3–1.5K input tokens, which is about $0.0017–0.0019 per image at the Standard $1.25/M input rate. Batching up to 50 images per call is possible.
- Use the Files API (`purpose="user_data"`) for images you reuse across calls. This also avoids the 413 `store=true` persistence failure that large inline base64 can trigger (see Q7).

### Gaps
- The docs give no maximum pixel dimensions and no `detail` parameter for images.
- I did not extract a video duration or frame-rate limit (the grep of the video doc found none).

## Q3. Structured output, JSON mode, tool calling, streaming

### Takeaway
JSON-schema structured output is supported: `response_format: {type: "json_schema", json_schema: {name, schema, strict}}` on Chat Completions, and `text.format` on Responses. The docs describe no separate `json_object` mode. Function calling uses `tools`, but `tool_choice` accepts only `"auto"`. Streaming is `stream: true` (SSE) on both APIs.

### Cited Findings
- "`text.format` is the Responses API parameter for structured output. `response_format` is the Chat Completions equivalent for structured output. A parameter from the other endpoint does not configure structured output, even when accepted for compatibility." — [Structured output](https://dev.meta.ai/docs/structured-output)
- Chat Completions shape: `response_format` with `type: "json_schema"` and a `json_schema` object containing `name`, `schema`, and optionally `strict`. The OpenAI SDK helper `client.beta.chat.completions.parse()` with a Pydantic model is shown, and the result is read from `.parsed`. — [Structured output](https://dev.meta.ai/docs/structured-output)
- Strict flag: "For structured output (`response_format` / `text.format`), the response is always constrained to your JSON Schema, so `strict: false` currently behaves the same as `strict: true` — output still conforms to the schema. The `strict` flag only controls whether the server additionally validates your schema against the strict subset". The Responses strict flag is `text.format.strict`, default `false`. — [Structured output](https://dev.meta.ai/docs/structured-output)
- Schema limits: recursive schemas are rejected (400). Nesting depth is 10, total properties 5,000, and enum values 1,000. — [Structured output](https://dev.meta.ai/docs/structured-output)
- The docs contain no mention of `json_object` (grep of the structured-output and chat-completions docs returned nothing). — [Structured output](https://dev.meta.ai/docs/structured-output)
- Tool choice: "**`tool_choice` must be `\"auto\"`**: Only `\"auto\"` (the default) is supported on both Chat Completions and the Responses API; `\"none\"`, `\"required\"`, and named function choices return `HTTP 400`". `parallel_tool_calls` defaults to `true`. "`functions` and `function_call` are deprecated." Tool arguments are "guided by your `parameters` schema but are not guaranteed to validate against it." — [Tool calling](https://dev.meta.ai/docs/tool-calling)
- Streaming tool arguments: on Chat Completions, accumulate `tool_calls` deltas by `index`. On Responses, consume `response.function_call_arguments.delta` events and finalize on `.done`. Responses text deltas arrive as `response.output_text.delta`, and the SDK helper is `client.responses.stream(...)`. — [Tool calling](https://dev.meta.ai/docs/tool-calling), [Responses API](https://dev.meta.ai/docs/protocols/responses)
- Unsupported or rejected Chat Completions parameters: `stop`, `n>1`, `logit_bias`, `logprobs: true` (400), `modalities` (400), `web_search_options`, and `reasoning_effort: "none"` (400 on Muse Spark). `max_output_tokens` is rejected on Chat Completions; use `max_completion_tokens` (`max_tokens` is still accepted). The docs recommend leaving `temperature` at its default of 1.0. — [Chat completion](https://dev.meta.ai/docs/protocols/chat-completions)
- Reasoning effort values: `"minimal"`, `"low"`, `"medium"`, `"high"`, `"xhigh"`, plus `"max"` on 1.3 Standard and Wonder. "Reasoning tokens are billed at the same rate as visible output tokens." — [Chat completion](https://dev.meta.ai/docs/protocols/chat-completions), [Reasoning](https://dev.meta.ai/docs/reasoning)

### Inferences
- For tagging or curating images into a fixed schema, use Responses with `text.format` json_schema, or Chat Completions with `response_format`. Because `tool_choice: "required"` is unavailable, structured output is the reliable way to force JSON.
- Use `reasoning_effort: "low"` or `"minimal"` for bulk tagging to cut latency and the cost of reasoning tokens.

### Gaps
- I did not capture a full verbatim Responses-API `text.format` request body. Per the docs it follows the OpenAI shape `text: { format: { type: "json_schema", name, schema, strict } }`, but that exact shape is not verified from a Meta example.

## Q4. Embeddings

### Takeaway
I found no embeddings endpoint or embedding model anywhere in the Meta Model API docs.

### Cited Findings
- The full docs index (llms.txt) lists Responses, Chat Completions, Messages, Files, Images, Voice, and Models. It has no embeddings page, and "embed" does not appear in the index. — [llms.txt](https://dev.meta.ai/llms.txt)
- The API reference nav sections are Responses, Chat completions, Messages, Files, Images, Voice, and Models. — [Models page nav](https://dev.meta.ai/docs/models)
- Probe: `POST https://api.meta.ai/v1/embeddings` without auth returned HTTP 401, which is inconclusive. The docs say unknown paths return 404 with an empty body, but auth may be checked before routing. — [Error handling](https://dev.meta.ai/docs/error-handling)

### Inferences
- For visual similarity in a design-reference app, plan on a third-party embedding model (for example open CLIP/SigLIP, or another provider). Another option is to have Muse Spark emit structured descriptive tags and embed those text tags elsewhere.

### Gaps
- An authenticated probe of `/v1/embeddings` was not done. Run one with a real key to confirm a 404.

## Q5. Rate limits, pricing, hackathon credit, billing

### Takeaway
Muse Spark 1.3 Standard costs $1.25 per 1M input tokens, $4.25 per 1M output, and $0.15 per 1M cached input, with limits of 3,000 RPM and 4M TPM per team. Contributor costs $0.10/$0.20 but is limited to 150 RPM, and your content may be used for training. The $150 hackathon credit comes through a claim form that needs your Team ID, must be submitted by Nov 4 9:00 PM ET, and is applied within about 2 business days. A payment method on file is required, and usage beyond the credits is charged to it automatically.

### Cited Findings
- Muse Spark Standard (1.3/1.2/1.1): cached input $0.15, input $1.25, output $4.25 per 1M. Contributor (`-contributor`): $0.002 / $0.10 / $0.20. Muse Wonder: $0.20 / $4.00 / $20.00, Standard only. Web search grounding is $2.50 per 1,000 queries. Muse Image is $0.01 per image. — [Pricing and rate limits](https://dev.meta.ai/docs/pricing-rate-limits)
- Contributor mode means "permission to use your content to train future Meta models." — [Pricing and rate limits](https://dev.meta.ai/docs/pricing-rate-limits)
- Rate limits are per team, not per key: Muse Wonder and Muse Spark 1.3/1.2/1.1 get 3,000 RPM and 4,000,000 TPM. Spark Contributor gets 150 RPM and 3,000,000 TPM. Muse Image gets 150 RPM. Headers: `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-tokens`, `x-ratelimit-limit-requests`, `x-ratelimit-remaining-requests`. The docs recommend exponential backoff with jitter starting around 500 ms. — [Pricing and rate limits](https://dev.meta.ai/docs/pricing-rate-limits)
- Credit Terms §1.2: "all Model API accounts require a valid payment method on file before the Services can be used". — [Hackathon Credit Terms PDF](https://scontent-lax3-2.xx.fbcdn.net/v/t39.8562-6/863382756_2547674092403265_4283663620107745955_n.pdf) (linked from [Cerebral Valley event page](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details))
- Credit Terms §2.1–2.2: the Claim Form asks for "your name, the email address used on your Hackathon application, your Account's Team ID". It is open "until **November 4, 2026 at 9:00 PM Eastern Time**". — [Credit Terms PDF](https://scontent-lax3-2.xx.fbcdn.net/v/t39.8562-6/863382756_2547674092403265_4283663620107745955_n.pdf)
- Credit Terms §3: "USD $150 in promotional Meta Model API credits", applied "within two (2) business days of a valid claim", and "Once applied, Hackathon Credits do not expire". "Once your Hackathon Credits are used up, further use of the Services is charged at standard pricing to the payment method on your Account ... You are responsible for monitoring your usage". — [Credit Terms PDF](https://scontent-lax3-2.xx.fbcdn.net/v/t39.8562-6/863382756_2547674092403265_4283663620107745955_n.pdf)
- The event page describes the credit differently: "$150 in Meta Model API credits, valid for a 10-day development window". This conflicts with Credit Terms §3.5 ("do not expire"), and the Credit Terms say they control for credits. — [Cerebral Valley event page](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details)
- Credit Terms §1.1(c): to claim, you must "reside in a country where the Services are available under the Meta Model API Geographic Use Policy". — [Credit Terms PDF](https://scontent-lax3-2.xx.fbcdn.net/v/t39.8562-6/863382756_2547674092403265_4283663620107745955_n.pdf)
- Hackathon dates: "Nov 4: Project submissions due by 9:00 PM ET". Submissions go to `https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit`. — [Cerebral Valley event page](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details)
- Billing error shape: HTTP 402 with `"type": "billing_error"` and `"code": "billing_not_configured"`. — [Error handling](https://dev.meta.ai/docs/error-handling)
- A secondary source reports a $20 signup credit for new Model API accounts, separate from the hackathon credit. This is unverified against Meta docs. — [search summary of press coverage, e.g. trendingtopics.eu](https://www.trendingtopics.eu/meta-opens-muse-spark-1-1-to-developers-and-bets-on-aggressive-pricing/)

### Inferences
- 9:00 PM ET on Nov 4 2026 falls after US DST ends (Nov 1), so it is EST (UTC-5) = 02:00 UTC Nov 5 = **07:30 IST Nov 5**. That matches the user's deadline, and the credit claim window closes at the same moment.
- $150 at Standard rates buys roughly 100K image analyses at about 1.4K input tokens each plus modest output. Reasoning output tokens dominate cost, so keep reasoning effort low.

### Gaps
- Spend limits or budget alerts: the pricing, auth, and error docs don't cover them. The Help Center (`/help`) did not return parseable Markdown. **Unverified** whether the dashboard has a hard spend cap.
- Rate-limit tiers or increases are not documented.

## Q6. Geographic availability (India)

### Takeaway
India is not a Restricted Territory. Only Muse Image is blocked from India (§2.2), so Muse Spark (all versions) and Muse Wonder are accessible from India per the policy text. Note that Pakistan and China/HK are fully restricted.

### Cited Findings
- §1 lists the Standard Models: Muse Image, Muse Spark 1.1/1.2/1.3, Muse Voice Transcribe, SAM 3.1, Muse Wonder, and Muse Wonder Full. — [Geographic Use Policy](https://dev.meta.ai/legal/geographic-use-policy)
- §2.2: "Certain Meta Models are not available in all jurisdictions where the Services are otherwise available." It names one model: **Muse Image: India**. You may not access Muse Image from India or make it available to End Users there. — [Geographic Use Policy](https://dev.meta.ai/legal/geographic-use-policy)
- §2.1: "You may not use technical measures to circumvent, bypass, or otherwise evade geographic access controls." — [Geographic Use Policy](https://dev.meta.ai/legal/geographic-use-policy)
- §3 Restricted Territories: Afghanistan, Belarus, Cambodia, PRC (incl. Hong Kong and Macau), Cuba, Eritrea, Ethiopia, Haiti, Iran, Iraq, Libya, Myanmar, Nicaragua, North Korea, Pakistan, Russia, Somalia, Syria, the Crimea/Donetsk/Luhansk regions, Venezuela, and Western Sahara. India is not listed. — [Geographic Use Policy](https://dev.meta.ai/legal/geographic-use-policy)
- Separately, Muse Wonder is unavailable in South Korea. — [Models](https://dev.meta.ai/docs/models)

### Inferences
- An India-based solo builder can use `muse-spark-1.3`, the Files API, and SAM 3.1, but must not call `muse-image-1.0` or `/v1/images/*`. The app must not offer Muse Image generation to Indian end users. Don't use a VPN to get around this (§2.1).

### Gaps
- §2.2 was read via a summarizing fetch. The ".md" version of the legal page 404'd, so the exact sentence about Muse Image in India is paraphrased, not verbatim. The policy's effective date was not captured.

## Q7. Gotchas: latency, errors, rate-limit codes

### Takeaway
Muse Spark is a reasoning model, so first-token latency can be long. One third-party benchmark reports about 39 s TTFT. Non-streaming requests can hit a server-side 504 timeout, so stream or use `background: true`. Watch for 429 `rate_limit_exceeded` with `Retry-After`, and for 413 when large base64 images are combined with `store=true`.

### Cited Findings
- Error envelope: `{"error": {"message": ..., "type": "invalid_request_error", "param": "top_p", "code": null}}`. `type` is one of `invalid_request_error`, `authentication_error` (401), `rate_limit_error` (429), or `server_error` (5xx). "A request to an unknown path returns `HTTP 404` with an **empty response body**". — [Error handling](https://dev.meta.ai/docs/error-handling)
- 429 example: `"message": "Rate limit exceeded. Please retry after 15 seconds.", "type": "rate_limit_error", "code": "rate_limit_exceeded"`. "The response includes a `Retry-After` header". — [Error handling](https://dev.meta.ai/docs/error-handling)
- 504 `gateway_timeout`: "Request exceeded the non-streaming server time limit before a response was produced. For large or slow requests, use the streaming API by setting \"stream\": true." The docs warn: "Do **not** simply retry". Instead, use `background: true`, stream, or lower `reasoning_effort`. — [Error handling](https://dev.meta.ai/docs/error-handling)
- 413 `payload_too_large` in two cases. First, a background request body over 1 MiB. Second, a `store=true` request "with large inline base64 media that succeeds at inference but is too large to persist". The fix is the Files API or `store=false`. Responses default to `store: true`. — [Error handling](https://dev.meta.ai/docs/error-handling), [Responses API](https://dev.meta.ai/docs/protocols/responses)
- 503 codes: `server_shutting_down`, `service_overloaded`, `backend_unavailable`. Mid-stream failures arrive as `response.failed` or `error` SSE events, not as HTTP status codes. — [Error handling](https://dev.meta.ai/docs/error-handling)
- Common setup errors: `401 invalid_api_key` and `404 model_not_found`. — [Quickstart](https://dev.meta.ai/docs/quickstart)
- Reasoning shares the output budget: if `max_output_tokens` is too low, the visible response may be truncated. — [Reasoning](https://dev.meta.ai/docs/reasoning)
- Third-party benchmark: about 39 s time to first token and about 110 output tok/s (attributed to Artificial Analysis). The source itself says results vary over time. — [computeprices.com](https://computeprices.com/models/muse-spark-1-3)
- Third-party: Muse Spark 1.3 was announced around Sep 2, 2026, with "max" reasoning held back at launch for safety testing. I could not verify this against Meta. — [aireiter.com review](https://aireiter.com/blog/muse-spark-1-3-api-pricing-review)

### Inferences
- In the UI, stream responses or run tagging as background jobs, and show progress. Don't block on synchronous calls. Store images via the Files API rather than inlining large base64 in `store=true` Responses calls, or set `store: false`.

### Gaps
- I found no developer forum or GitHub issue reports specific to the Meta Model API. The latency figure comes from a single third-party aggregator, so treat it as indicative only.
