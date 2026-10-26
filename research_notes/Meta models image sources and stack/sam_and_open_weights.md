# SAM 3.1 (Meta Model API) and Muse Spark Open (Baseten / Modal): interface notes, as of 2026-10-26

Legend: **[VERIFIED]** = read on a primary page this session. **[UNVERIFIED]** = secondary source, inference, or user's notes not confirmed.

## Q1. SAM 3.1 on the Meta Model API: endpoint, auth, prompts, request and response shapes, limits, pricing, SDK

### Takeaway
SAM 3.1 is model `sam-3.1` on the OpenAI-style **Responses API** (`POST https://api.meta.ai/v1/responses`, Bearer key). It takes one `input_text` (a noun phrase OR box/point token prompts) plus an `input_image` or `input_video`. It returns **special-token text, not JSON**: one line per frame of `<Nf>` + records `id<|box;...|><|mask;...|>`. The masks are base85 payloads. The official parser libraries (`@meta-sam/parser`, `meta-sam-parser`) decode them to a raster, COCO RLE or an SVG path. Pricing is $2.50 per 1,000 images and $0.20 per 1,000 video frames (50-frame minimum per video request). The limit is 3,000 RPM.

### Cited Findings
**Endpoint and auth [VERIFIED]**
- `POST https://api.meta.ai/v1/responses` (SDK base URL `https://api.meta.ai/v1`). Header `Authorization: Bearer <MODEL_API_KEY>`. Streaming examples also send `Content-Type: application/json` and `Accept: text/event-stream`. — [SAM segmenting](https://dev.meta.ai/docs/sam/segmenting)
- The model ID is `sam-3.1`. Streaming is recommended for video and optional for images. — [SAM overview](https://dev.meta.ai/docs/sam/overview)
- Files API: `POST https://api.meta.ai/v1/files`, multipart with `purpose=user_data` and `file`. A 200 means the file is ready, and the response has `id` and `status: "uploaded"`. — [SAM segmenting](https://dev.meta.ai/docs/sam/segmenting)

**Request body [VERIFIED]** — [SAM segmenting](https://dev.meta.ai/docs/sam/segmenting)
- `model: "sam-3.1"`
- `input`: one user message whose `content` holds:
  - `{type:"input_text", text:"<noun phrase>"}`, or box/point token prompts. A request carries one or the other, not both.
  - `{type:"input_image", image_url:"<public URL or base64 data URL>"}`
  - `{type:"input_video", video_url:...}` or `file_id` from the Files API
- `stream: true` (recommended for video)
- `metadata` (all values are **strings**):
  - `include_confidence: "true"|"false"`. Adds `c` (0 to 1) to boxes and masks.
  - `mask_encoding: "lossless"` (default, marker `~`) or `"one_bit"` (marker `!`, smaller). Box/point prompts always return `one_bit`.
  - `propagation_direction: "both"` (default), `"forward"` or `"backward"` (video).
- The exact JSON nesting (`input:[{role:"user",content:[...]}]`) follows the Responses protocol. The page shows the part types but I did not copy a literal full JSON body. **[UNVERIFIED as literal]** Check against [Responses API](https://dev.meta.ai/docs/protocols/responses).

**Prompt types [VERIFIED]** — [SAM segmenting](https://dev.meta.ai/docs/sam/segmenting)
- *Concept (text):* one short noun phrase, e.g. `"red hat"`. It returns **every matching instance**, so you get multiple instances per prompt.
- *Box/point token grammar:* `<Nf>` (frame), `<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>`, `<|point;x=..;y=..;w=..;h=..|>`. A `-` prefix on a point makes it a negative point. Object ids are comma-separated. `w`/`h` must be the media's **displayed pixel size**, so convert preview coordinates to media pixels first.
- Image prompts must be on frame 0.

**Prompting rules [VERIFIED]** — [SAM segmenting](https://dev.meta.ai/docs/sam/segmenting); [SAM overview](https://dev.meta.ai/docs/sam/overview)
- Use a short noun phrase for one object. No commands or questions.
- Send **one concept per request**. Lists, "and" and newlines don't work, so multiple object types need multiple requests.
- Attributes such as colour or type narrow the matches. Formatting, plurals and case don't matter.
- Avoid negation, OR and spatial phrases. Filter by position client-side using the returned boxes.
- Meta suggests pairing Muse Spark (scene understanding) with SAM 3.1 (segmentation).

**Response format [VERIFIED]** — [Reading segmentation output](https://dev.meta.ai/docs/sam/reading-segmentation); [SAM segmenting](https://dev.meta.ai/docs/sam/segmenting)
- Output arrives as SSE. Each frame is one `response.output_text.delta` event containing one line, and `response.completed` ends the stream.
- A line is a frame marker `<Nf>` (zero-based, indices may skip), then **comma-separated records**. Each record is an object id, then a box, then a mask, e.g. `<0f>0<|box;...|><|mask;x=0;y=0;data=...|>`.
- An image is a single line `<0f>...`. A video emits one line per frame that has visible objects. With `both`, frames can arrive out of order.
- Object ids are stable across frames but **not dense or 0-based**, so key by id.
- Box fields: `x1,y1` (top-left) and `x2,y2` (bottom-right) in source pixels, plus `w,h` (source size, repeated on every record). Optional `c` comes after `h`.
- Mask fields: `x=0;y=0` (always literal 0), optional `c` between `y` and `data`, and `data=H,W,<marker>payload`. `H`/`W` are smaller than the frame. The marker is the first character after `H,W,` (`~` lossless, `!` one_bit). The payload is **base85** (not base64) and may itself contain `~` or `!`.
- `c` is per frame. The only score field is `c`, and it appears only with `include_confidence`.
- Zero matches give `response.completed` with an empty `output_text` and no delta events.
- The **wire format is neither RLE nor polygons**. The client libraries convert it to COCO RLE or SVG paths (see SDK below).

**Video [VERIFIED]** — [SAM segmenting](https://dev.meta.ai/docs/sam/segmenting)
- Containers are MP4 or MOV with H.264, H.265 or MPEG-4. VP9 and WebM are rejected.
- Up to 15,000 frames (about 10 minutes) per request.
- **Tracks up to 16 objects per frame.** Box/point prompts can name up to 16 objects.
- Propagation: `both` (earliest prompt to end, then back to 0), `forward`, or `backward` (needs a prompt after frame 0).
- Export with MP4 faststart to skip server-side remuxing.

**Errors [VERIFIED]:** `400` means an invalid prompt or metadata; fix it rather than retrying unchanged. `404 model_not_found` means checking the model ID and account access. — [SAM segmenting](https://dev.meta.ai/docs/sam/segmenting)

**Pricing and limits [VERIFIED]** — [Pricing & rate limits](https://dev.meta.ai/docs/pricing-rate-limits)
- Images cost $2.50 per 1,000 ($0.0025 each). Video costs $0.20 per 1,000 frames, with a minimum of 50 frames billed per video request. Streaming and non-streaming cost the same.
- SAM 3.1 allows 3,000 RPM with no TPM limit. Concurrency is not specified, and limits apply per team.
- For comparison, Muse Spark (hosted) costs $1.25 input, $0.15 cached and $4.25 output per 1M tokens. `muse-spark-1.3/1.2/1.1` get 3,000 RPM and 4M TPM. Contributor mode is $0.10/$0.20 with 150 RPM. — same page

**SDK helpers [VERIFIED]** — [Client libraries](https://dev.meta.ai/docs/sam/client-libraries)
- `npm install @meta-sam/parser` (zero dependencies, ESM only, Node `^20.17.0` or `>=22.9.0`). `pip install meta-sam-parser` (import name `meta_sam_parser`, Python 3.10+, zero dependencies). Optional packages: `@meta-sam/graphics` (canvas overlays), `@meta-sam/video`, `@meta-sam/react`.
- TypeScript: `parseImageStream(events)` and `parseVideoStream(events)` take an `AsyncIterable<ResponsesEvent>` and return snapshots plus a `.finalResult` promise. Also `recordsOfKind(records, "mask"|"box")`, `buildObjectPrompt({size:{width,height}, objects:[{id, prompts:[{frame?, box:{left,top,right,bottom}} | {frame?, points:[{x,y,label?:"negative"}]}]}]})`, `decodeMaskToRaster(mask): Uint8Array` (row-major 0/1, length W*H), `decodeMaskToRLE(mask): {size:[h,w], counts}` (COCO) and `decodeMaskToSVGPath(mask): string`.
- Python: `build_object_prompt(size=(w,h), objects=[PromptObject(id=1, prompts=[FramePrompt(frame=30, box=PromptBox(10,20,40,60)), FramePrompt(frame=120, points=[PromptPoint(20,40), PromptPoint(30,50,label="negative")])])])`, plus `decode_mask_to_raster`, `decode_mask_to_rle` and `decode_mask_to_svg_path`.
- Version gates: `buildObjectPrompt`/`build_object_prompt` need 0.1.0+. Confidence parsing needs `@meta-sam/parser` 0.0.13+ or `meta-sam-parser` 0.0.6+.

### Inferences
- For an image adapter: send a non-streaming or streaming request with one noun phrase and the image URL or data URL, plus `mask_encoding:"one_bit"` and `include_confidence:"true"`. Feed the events to the parser, then call `decode_mask_to_rle` or `decode_mask_to_svg_path`. Don't hand-parse base85.
- Multi-concept segmentation means N parallel requests at $0.0025 each, which fits comfortably under 3,000 RPM.

### Gaps
- Image size and format limits, and latency, are not stated in the overview, segmenting or client-library pages.
- I did not confirm the exact Python parsing entry-point names, since the client-libraries page only says they "mirror" the TypeScript ones. The non-streaming response JSON envelope (`output[].content[].text`) was not shown verbatim.
- Free credit: a secondary source says new accounts get $20 ([Medium](https://medium.com/@isaakmwangi2018/meta-muse-spark-1-1-tutorial-benchmarks-pricing-5dc7aa1f08f8)). A hackathon newsletter says $150 in Meta Model API credits ([Sequenzy copy of email](https://www.sequenzy.com/api/email-examples/j5iypr0umhagob6hpglchdwg/html)). **[UNVERIFIED]**

## Q2. Are SAM 3 / 3.1 weights open?

### Takeaway
Yes, but the weights are **gated** on Hugging Face under the custom **SAM License**, and the code lives at `github.com/facebookresearch/sam3`. Local or Modal self-hosting is possible once access is approved, though approval is not guaranteed in time.

### Cited Findings
- `facebook/sam3.1` on Hugging Face: license "other", gated (you share HF info under the Meta Privacy Policy), no Transformers integration. It points to https://github.com/facebookresearch/sam3 for code. — [HF facebook/sam3.1](https://huggingface.co/facebook/sam3.1)
- New in 3.1: "Object Multiplex", shared-memory multi-object tracking that runs about 7x faster at 128 objects on a single H100, with VOS improved on 6 of 7 benchmarks. No inference provider currently deploys it on HF. — [HF facebook/sam3.1](https://huggingface.co/facebook/sam3.1)
- The SAM License (updated Nov 19, 2025) is a non-exclusive, worldwide, royalty-free limited license to use, modify and distribute. Redistribution must include the agreement, and published research must acknowledge use. — [HF sam3 LICENSE](https://huggingface.co/facebook/sam3/blob/main/LICENSE) (via search snippet)
- HF discussion threads report rejected access requests on `facebook/sam3` and `facebook/sam3.1`. — [HF discussion](https://huggingface.co/facebook/sam3/discussions/329)
- Meta's own docs say the family was "originally released as open-weight research models". — [SAM overview](https://dev.meta.ai/docs/sam/overview)

### Inferences
- With the Nov 5 deadline, the hosted API is the safer path. Request HF access now if you want a Modal fallback.

### Gaps
- I did not read the full license text for commercial-use wording. GPU memory needs for SAM 3.1 are not stated.

## Q3. Muse Spark Open: license, size, repo, context, modalities

### Takeaway
Muse Spark Open is an 816B-total / 42B-active MoE with a 1M context. It takes text, image, video and audio in and produces text. It was released on Oct 15 2026 at HF `meta-models/Muse-Spark-Open-816B-A42B` (BF16 and NVFP4) under the **Muse Model License**. It is far too large for a solo builder to self-host: NVFP4 needs at least 700 GB of VRAM.

### Cited Findings
- **License [VERIFIED]:** Muse Model License (Oct 15 2026). You must display "Built with Muse Spark Open". MaaS providers with more than $20M in annual gross revenue need a separate agreement. The Exhibit A usage policy applies, and use by people under 18 is restricted. Meta claims no ownership of outputs. — [HF model card](https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B)
- **Size and specs [VERIFIED]:** 816B total and 42B active (safetensors shows 822B). Formats are BF16 and NVFP4 (Baseten references a `Muse-Spark-Open-816B-A42B-NVFP4` repo). Context is 1M. Input is text, image, video and audio, and output is text. NVFP4 needs at least 700 GB of VRAM and BF16 about 2 TB. It is optimised for two M5 Ultra Mac Studios with MLX. — [HF model card](https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B); [Baseten library](https://www.baseten.co/library/muse-spark-open/)
- **Serving [VERIFIED]:** `vllm serve "meta-models/Muse-Spark-Open-816B-A42B"` (OpenAI API on :8000). SGLang: `python3 -m sglang.launch_server --model-path ... --port 30000`. Also Transformers (`AutoModelForMultimodalLM`), TensorRT-LLM and llama.cpp. Versions are not given. — [HF model card](https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B)
- **Reasoning [VERIFIED]:** `reasoning_effort` is one of low, medium, high or xhigh (default **xhigh**; any other value errors). It can also go through `chat_template_kwargs`. Recommended sampling is temperature 1.0, top_p 1.0 and no top_k. — [HF model card](https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B)
- Meta does **not** serve it on its own Model API. It is available through Together, Fireworks, OpenRouter, Baseten, Modal and others. — [benchmarklist](https://benchmarklist.com/models/meta-muse-spark-open/) (secondary); [Modal blog](https://modal.com/blog/meta-muse-spark-open-now-available-on-modal)

### Inferences
- Default xhigh reasoning will add latency and output tokens. Set `reasoning_effort:"low"` or `"medium"` for UI-facing calls, if the host passes it through (unverified per host).

### Gaps
- Tool-call format, chat template contents and structured-output support are not documented on the model card.

## Q4. Baseten: model id, endpoint, auth, OpenAI compatibility, credit

### Takeaway
Baseten serves it through an OpenAI-compatible Chat Completions API: base URL `https://inference.baseten.co/v1`, header `Authorization: Bearer $BASETEN_API_KEY`, model `meta-models/muse-spark-open`. Pricing is $1.25 input, $0.15 cached and $4.25 output per 1M tokens. The user's id `meta-models/muse-spark-open-1026` **does not appear** in Baseten's pages.

### Cited Findings
- `POST https://inference.baseten.co/v1/chat/completions` with Bearer Baseten API key. It is "OpenAI-compatible". Inputs are text, image, audio and video, and output is text. — [Baseten changelog](https://www.baseten.co/resources/changelog/muse-spark-open-and-nemotron-35-super-vl-available-on-baseten/)
- Verbatim sample: `OpenAI(base_url="https://inference.baseten.co/v1", api_key=os.environ["BASETEN_API_KEY"])`, then `client.chat.completions.create(model="meta-models/muse-spark-open", messages=[{"role":"developer",...},{"role":"user",...}])`. Note it uses the `developer` role. Pricing per 1M tokens: $1.25 input, $0.15 cached, $4.25 output. The dedicated-deployment slug is `muse-spark-open-816b-a42b`. — [Baseten library](https://www.baseten.co/library/muse-spark-open/)
- Neither Baseten page mentions a context length, rate limits, `response_format`/JSON mode, or the tool-call schema. — [Baseten library](https://www.baseten.co/library/muse-spark-open/)

### Inferences
- Use `meta-models/muse-spark-open` unless the hackathon credit email names `-1026`. A `-1026` suffix may be a dated snapshot (Oct 2026) on a hackathon-specific deployment. **[UNVERIFIED]** Test with a 1-token call, and on a 404 fall back to the other id.
- Image input should work with OpenAI-style `{"type":"image_url","image_url":{"url":...}}` content parts. **[UNVERIFIED]** Baseten shows no image example.

### Gaps
- I could not verify the hackathon credit terms ($100, 2M TPM, review-based). The Cerebral Valley page redirects to login, and no public Baseten page mentions them. Baseten's general startup program lists up to $2,500 for Model APIs, which is unrelated. — [Baseten startup program](https://www.baseten.co/startup-program/)

## Q5. Modal: deployment approach, GPUs, credit

### Takeaway
You don't need to self-deploy. Modal offers Muse Spark Open as a **Shared Endpoint (Auto Endpoints) with per-token billing**, model `meta-models/Muse-Spark-Open-816B-A42B`. Self-deploying with vLLM or SGLang would need at least 700 GB of VRAM (for example, 8 or more large GPUs). That is impractical for a $100 credit.

### Cited Findings
- "Now available on Modal Auto Endpoints… runs on Modal as a Shared Endpoint with per-token billing". The console link is `modal.com/endpoints?model=meta-models%2FMuse-Spark-Open-816B-A42B&type=shared`. Modal's general offer is $30/month of free compute. — [Modal blog](https://modal.com/blog/meta-muse-spark-open-now-available-on-modal)
- The blog gives no endpoint URL, auth scheme, per-token price, OpenAI-compatibility statement or code. — [Modal blog](https://modal.com/blog/meta-muse-spark-open-now-available-on-modal)

### Inferences
- The Shared Endpoint is probably OpenAI-compatible, as is typical of Modal's LLM serving. **[UNVERIFIED]** Read the URL and token from the Modal endpoints console.
- Modal is most useful for self-hosting **SAM 3.1** (single-GPU class, benchmarked on one H100) if HF access is granted. Hardware needs are not documented.

### Gaps
- I did not fetch the Modal Auto Endpoints docs, pricing or $100 hackathon credit terms. Modal SAM 3 example code was not checked.

## Q6. Image input and JSON/structured output on these hosts

### Takeaway
Image input is supported by the model and listed by Baseten. No source documents structured output or JSON mode for Muse Spark Open on Baseten or Modal.

### Cited Findings
- Baseten lists image among the input modalities. — [Baseten changelog](https://www.baseten.co/resources/changelog/muse-spark-open-and-nemotron-35-super-vl-available-on-baseten/)
- The HF card says nothing about structured output. — [HF model card](https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B)
- Modal claims "native multimodal understanding". — [Modal blog](https://modal.com/blog/meta-muse-spark-open-now-available-on-modal)

### Inferences
- Use `response_format: {"type":"json_schema", ...}` defensively: validate the result and retry with a "JSON only" prompt if the parameter is rejected or ignored. vLLM and SGLang backends usually support guided decoding, but that is **[UNVERIFIED]** for these hosts.

### Gaps
- No primary confirmation of `response_format`, tool calling or image-part schema on either host.

## Q7. Hackathon rule for the "Best Build on Meta Open Weight Models" bonus

### Takeaway
**Unverified.** The Cerebral Valley details page requires login and could not be read. Meta's public hackathon page doesn't mention this category or any Baseten or Modal credits.

### Cited Findings
- `cerebralvalley.ai/e/meta-ai-developer-hackathon/details` renders "Loading..." to a fetcher and redirects a headless browser to `/auth/login`. (Tested this session.)
- The official page lists a $1M pool across two tracks (Indie Developer and Startup) and themes "Build for Your World" and "Push the Frontier". Tools: the Muse Spark series, Muse Image and SAM 3.1 via the Meta Model API, "Meta open weights models", Muse Code, and a link to Muse Spark Open. Submissions are due **Nov 4, 9:00 PM ET (Nov 5, 7:30 AM IST)**, judging runs Nov 4 to 8, and winners are announced Nov 9. India is not on the exclusion list. No "Best Build on Meta Open Weight Models" category or partner credits appear. — [dev.meta.ai global hackathon](https://dev.meta.ai/events/global-hackathon)
- A newsletter mentions $150 in Meta Model API credits and open-weights models as a build option, with no open-weight bonus described. — [Sequenzy email copy](https://www.sequenzy.com/api/email-examples/j5iypr0umhagob6hpglchdwg/html)

### Inferences
- A defensible guess (unverified) is that qualifying requires a core feature to run on Muse Spark Open (or another Meta open-weight model such as SAM 3.1 weights) through Baseten, Modal or self-hosting, visible in the demo and code. Also honour the license's "Built with Muse Spark Open" attribution. Hosted `sam-3.1` on the Meta API is probably *not* "open weight" usage. Confirm in the logged-in Cerebral Valley page or Discord.

### Gaps
- The exact bonus criteria, the Baseten $100 / 2M TPM review-based credit, and the Modal $100 credit terms were all unverifiable (login wall).
