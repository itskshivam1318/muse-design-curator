# Technical stack and retrieval approach for a 9-day attribute-aware image retrieval build (Muse Spark + SAM 3.1)

Research date: 2026-10-26. Items marked **[UNVERIFIED]** come from the researcher's background knowledge (training cutoff mid-2026) and were not confirmed against a live source in this session. Check them before relying on them.

## 0. Platform facts that constrain everything else (Meta Model API)

### Takeaway
Muse Spark and SAM 3.1 are both served from the same OpenAI-SDK-compatible Meta Model API (`https://api.meta.ai/v1`). That makes the backend language mostly a matter of preference for the LLM calls. **The biggest risk is not language choice. It is that the public preview was documented as US-only, and the builder is in India.** Confirm API key access on day 1.

### Cited Findings
- Base URL `https://api.meta.ai/v1`. Model `muse-spark-1.1` was the launch model. The API is "OpenAI SDK–compatible" (Chat Completions + Responses formats) and also accepts the Anthropic Messages format. Image input goes in as an `image_url` content part (base64 data URL or public URL). The blog post is dated Jul 08, 2026. — [Meta dev blog: Build with Muse Spark](https://dev.meta.ai/resources/blog/build-with-muse-spark/)
- "The public preview is available to developers in the US". India is not mentioned. Pricing: $1.25 in / $4.25 out per 1M tokens, with reasoning tokens billed as output. Other features: `reasoning_effort` (minimal→xhigh), built-in `web_search`, streaming, prompt caching. — [Meta dev blog](https://dev.meta.ai/resources/blog/build-with-muse-spark/)
- The current docs list these models: `muse-spark-1.3`, `muse-spark-1.2`, `muse-spark-1.1` (and `-contributor` variants), `muse-wonder-1.0`, `muse-image-1.0`, `muse-voice-transcribe-1.0`, **`sam-3.1`**. SAM 3.1 is reached via `POST /v1/responses` and `POST /v1/files`. It takes a text prompt, image or video, and returns "a box and a pixel-accurate mask for every match". The docs say the API is compatible with the OpenAI SDK, the Anthropic SDK and OpenAI-compatible clients, and show Python and TypeScript quickstarts. — [Meta Model API docs](https://dev.meta.ai/docs/)
- Third-party coverage reports the API as public preview: the US is in, the EU is not, and new accounts get $20 free credits. It also reports structured output, parallel tool calling, a Files API, and a context window of 1,048,576 tokens. The Meta Model API replaced the Llama API, which was retired in early July 2026. — [ProPakistani, 2026-07-11](https://propakistani.pk/2026/07/11/meta-launches-muse-spark-1-1-with-its-first-paid-ai-model-api/); [Promptfoo Meta provider docs](https://www.promptfoo.dev/docs/providers/meta/) (secondary; the $20 credit is not in Meta's own blog)
- The OpenAI SDK does not auto-read `MODEL_API_KEY`, so pass `api_key` and `base_url` explicitly. — [Promptfoo / search summary](https://www.promptfoo.dev/docs/providers/meta/) (secondary)
- Self-hosting SAM 3 weights is not an easy fallback. The `facebook/sam3` HF repo is gated under a custom "SAM License" (dated Nov 19, 2025), and users report rejected or slow access requests, some mentioning SAM 3.1 specifically. — [facebook/sam3 LICENSE](https://huggingface.co/facebook/sam3/blob/main/LICENSE); [HF discussion #440](https://huggingface.co/facebook/sam3/discussions/440)
- Hosted SAM 3 wrappers (Roboflow, fal.ai, WaveSpeed) return masks as **COCO RLE**, which "can be decoded with pycocotools". fal.ai lists $0.005/request. — [Roboflow SAM3 block](https://docs.roboflow.com/workflows/blocks/blocks/run-a-model/sam3); [fal.ai SAM 3](https://fal.ai/models/fal-ai/sam-3/image); [WaveSpeed sam3-image-rle](https://wavespeed.ai/de/models/wavespeed-ai/sam3-image-rle)

### Inferences
- The same OpenAI client and the same key cover both the VLM and segmentation. Write one thin `meta_client` wrapper.
- If the India API key does not work, the fallback for segmentation is a hosted SAM 3 endpoint (fal.ai or Replicate-style) returning COCO RLE. That again favours a Python backend with `pycocotools`. There is no equivalent fallback for Muse Spark itself, so access must be confirmed first.

### Gaps
- The exact SAM 3.1 API mask encoding (RLE, PNG or polygon) was not documented on the docs index page.
- Image size and format limits, rate limits, and India availability as of Oct 2026 were not found on official pages.
- Whether `response_format: {type: "json_schema"}` is supported in Chat Completions or only in Responses was not confirmed.

## 1. Backend: Python FastAPI vs Next.js/TypeScript route handlers

### Takeaway
**Use Python (FastAPI) for the backend and keep Next.js/React only for the front end.** Every non-LLM piece of this workload has mature Python libraries and weak or missing JS equivalents: COCO RLE decode, mask-applied crops, CIELAB k-means, and open_clip/transformers embeddings. The LLM SDK is the one piece that is a draw between the two languages.

### Cited Findings
- The Meta Model API is OpenAI-SDK-compatible and the docs show both Python and TypeScript quickstarts, so the LLM SDK story is equal. — [Meta Model API docs](https://dev.meta.ai/docs/)
- SAM 3 RLE output "can be decoded with pycocotools" (COCO-compatible). — [WaveSpeed sam3-image-rle](https://wavespeed.ai/de/models/wavespeed-ai/sam3-image-rle)
- Embedding models (OpenCLIP, SigLIP 2, PE-Core, Marqo-FashionSigLIP) ship as PyTorch / open_clip / timm / transformers checkpoints. For example, PE-Core has timm cards, and Marqo-FashionSigLIP is an open_clip `hf-hub:` model. — [timm/PE-Core-L-14-336](https://huggingface.co/timm/PE-Core-L-14-336); [Marqo-FashionSigLIP card mirror](https://huggingface.co/pySilver/marqo-fashionSigLIP-ST)
- **[UNVERIFIED]** JS options exist but are thinner:
  - `sharp` (libvips) handles resize and crop well.
  - Transformers.js runs some CLIP and SigLIP ONNX exports in Node. PE, FashionSigLIP and DINOv3 ONNX availability is spotty.
  - There is no maintained JS pycocotools. COCO RLE decode is about 40 lines to hand-write, plus a compressed-string LEB128-like decoder.
  - k-means in CIELAB needs `ml-kmeans` + `culori`/`chroma-js`.
- **[UNVERIFIED] Library picks (Python):**
  - `fastapi` 0.11x + `uvicorn`
  - `pillow` 11.x and/or `opencv-python-headless` 4.1x
  - `pycocotools` 2.0.x (has macOS arm64 wheels)
  - `numpy` 2.x
  - `scikit-learn` `KMeans`/`MiniBatchKMeans` for palettes
  - `scikit-image` `rgb2lab` and `deltaE_ciede2000` for colour distance
  - `open_clip_torch` 3.x
  - `transformers` 4.5x
  - `openai` Python SDK 1.x/2.x

### Inferences
- Use Next.js (or Vite + React) only as the moodboard UI and call FastAPI over JSON. This keeps the ML in one process and avoids two embedding runtimes.
- Palette extraction should be: SAM mask → masked pixels → convert to Lab → k-means (k=5) → sort by cluster weight. Colour similarity should use ΔE2000 rather than RGB cosine. This is the one attribute where you should compute rather than ask the VLM, because it is deterministic and explainable.
- Cosine similarity at a 20k scale is a single `numpy` matmul (20k×768 float32 ≈ 61 MB). No special library is needed.

### Gaps
- Exact current versions of FastAPI, open_clip, transformers and pycocotools were not fetched live. Pin from `pip index versions` on day 1.

## 2. Image embeddings for attribute-aware retrieval

### Takeaway
**Use a text-aligned model as the single global embedder. Recommended: SigLIP 2 base (`google/siglip2-base-patch16-256/384`) or Meta PE-Core-B16-224 (Apache-2.0). Add Marqo-FashionSigLIP only if fashion is the hero domain.** Skip DINOv3 for the main index: its license is custom and it has no native text tower. DINOv2 is a good optional image-only "same item" signal, but it loses badly to SigLIP 2 on fine-grained fashion retrieval. No embedding model reliably encodes "same item, different colour". Handle colour and other attributes explicitly with VLM JSON and Lab palettes, not with embeddings.

### Cited Findings
- **PE-Core (Meta Perception Encoder):** HF model-card metadata for `facebook/PE-Core-B16-224` and `PE-Spatial-G14-448` was set to `license: apache-2.0`. A LiteRT port also states Apache-2.0. timm hosts `PE-Core-L-14-336`. — [PE-Core-B16-224 commit](https://huggingface.co/facebook/PE-Core-B16-224/commit/f1ebc681f0cd27604bb96b2d8f48dbc72ae7b05d); [PE-Spatial commit](https://huggingface.co/facebook/PE-Spatial-G14-448/commit/ead5c2c1915eec7ca4e1f96df9d094106f0aabf4); [timm PE-Core-L-14-336](https://huggingface.co/timm/PE-Core-L-14-336); [LiteRT port](https://huggingface.co/mlboydaisuke/PE-Core-base-patch16-224-LiteRT). The GitHub repo's license was not confirmed by one aggregator ([sourcepulse](https://www.sourcepulse.org/projects/2366364)).
- **DINOv3:**
  - Custom "DINOv3 License" (Aug 14, 2025). It is royalty-free, but redistribution must include the agreement and prominently display "Built with DINOv3", and published research must acknowledge it. — [DINOv3 License](https://ai.meta.com/resources/models-and-libraries/dinov3-license)
  - A GitHub issue calls the custom license a legal-review burden compared with DINOv2's Apache-2.0. — [dinov3 issue #31](https://github.com/facebookresearch/dinov3/issues/31)
  - The text-aligned variant follows the dino.txt recipe. — [DINOv3 paper, arXiv 2508.10104](https://arxiv.org/pdf/2508.10104)
  - The dino.txt authors note it is lower than SigLIP on text-image retrieval. — [dino.txt, arXiv 2412.16334](https://arxiv.org/pdf/2412.16334)
- **Fine-grained fashion evidence (LookBench, arXiv 2601.14706, Jan 2026):** Fine Recall@1 is **SigLIP2-B/16 59.44** vs **DINOv2-ViT-L 41.07** and **DINOv2-ViT-G 41.49**. The table also includes DINOv3 and CLIP, but those numbers were not extracted. LookBench uses "attribute-supervised evaluation with over 100 visually grounded properties". — [LookBench PDF](https://arxiv.org/pdf/2601.14706) (numbers from the search-result snippet, as PDF extraction failed); [LookBench page](https://serendipityoneinc.github.io/look-bench-page)
- **Marqo-FashionSigLIP:**
  - About 203M params, fine-tuned from ViT-B-16-SigLIP (webli) with Generalised Contrastive Learning over categories, colours, materials, etc.
  - Vendor claim of "up to 57%" MRR/recall improvement over FashionCLIP.
  - Listed as Apache-2.0.
  - A successor, marqo-fashionSigLIP-2, claims a further 78% improvement (vendor claim).
  - Sources: [model card mirror](https://huggingface.co/pySilver/marqo-fashionSigLIP-ST); [Superlinked listing](https://superlinked.com/models/marqo-marqo-fashionsiglip.md); [third-party analysis](https://hopitai.substack.com/p/beating-fashionsiglip)
- Anecdotal (Reddit, 175 train / 132 test images): SigLIP2 SO400M ~92% vs DINOv2-G ~41% on fine-grained car k-NN. This is a weak signal. — [Reddit snapshot](https://reddit.sentinel-team.org/posts/1uqtamz/snapshots/2026-07-09T20%3A50%3A09.14801Z)
- **[UNVERIFIED]** Background facts:
  - OpenCLIP: MIT code, weights under various licences.
  - SigLIP 2 (Feb 2025): Apache-2.0, multilingual, has NaFlex variants, and is in transformers and open_clip.
  - FashionCLIP (patrickjohncyh/fashion-clip): MIT.
  - DINOv2: Apache-2.0, no text tower, so no text-to-image search.
  - Base-size ViT-B/16 at 224–256 px embeds at roughly 20–60 ms/image on Apple Silicon MPS and ~100–300 ms on a laptop CPU. A 20k corpus therefore takes about 10–60 min to index offline, which is acceptable.

#### Capability matrix

| Model | Text→image query | Crop / mask region embedding | CPU / Apple Silicon | License |
|---|---|---|---|---|
| OpenCLIP ViT-B/16 | Yes | Crop then embed | Yes (base size) | MIT code; weights vary **[UNVERIFIED]** |
| SigLIP 2 B/16 | Yes | Crop then embed | Yes | Apache-2.0 **[UNVERIFIED]** |
| PE-Core B16 / L14 | Yes | Crop then embed. PE-Spatial is for dense features | Yes (B16) | Apache-2.0 (HF metadata) |
| DINOv2 | No | Crop or patch tokens | Yes | Apache-2.0 **[UNVERIFIED]** |
| DINOv3 | Only via dino.txt variant | Strong dense features | ViT-S/B yes | Custom DINOv3 License, needs attribution |
| FashionCLIP / Marqo-FashionSigLIP | Yes (fashion-tuned) | Crop then embed | Yes | MIT **[UNVERIFIED]** / Apache-2.0 |

### Inferences
- For "region" embeddings, take the SAM 3.1 mask, compute its bounding-box crop, and paint the background neutral grey (or alpha-composite onto the mean colour). Then embed with the same global model. This is simpler and more robust than pooling patch tokens under the mask, which is research-grade work you do not have time for.
- Global CLIP/SigLIP embeddings entangle colour with identity. Same shoe in a different colour often ranks *below* a different shoe in the same colour. Mitigate this two ways. (a) Embed a **greyscale** copy as an extra "shape/identity" vector when the varied attribute is colour. (b) Score colour separately with a Lab palette ΔE. This is an inference from known CLIP behaviour **[UNVERIFIED]**, and the LookBench fine-recall gap suggests fine attributes are hard even for the best models.
- Pick one model for all four domains (watches, fashion, interiors, UI screens). A fashion-specific model will degrade on UI screenshots. PE-Core or SigLIP 2 are generalist.

### Gaps
- No live CPU or MPS latency benchmarks were found for SigLIP 2, PE-Core or DINOv3. Benchmark on day 1 with 100 images.
- PE-Core and DINOv3 numbers on LookBench were not extracted.
- No public benchmark exists for UI-screen or watch attribute retrieval.

## 3. Composed image retrieval (CIR) and whether the simple pipeline is a sound baseline

### Takeaway
**Yes. "VLM attribute JSON + modified target description + embedding retrieval + rerank" is essentially the published training-free zero-shot CIR recipe (CIReVL, ICLR 2024; TFCIR; MCoT-RE 2025).** It is a defensible baseline and the right scope for 9 days. Training Pic2Word/LinCIR-style inversion networks is out of scope.

### Cited Findings
- The 2025 CIR survey (arXiv 2502.18495) groups zero-shot CIR into three families: textual-inversion (Pic2Word, SEARLE, LinCIR), pseudo-triplet, and training-free. It benchmarks on FashionIQ, CIRR and CIRCO. LinCIR (CLIP-G) averages 55.40 on FashionIQ, which is competitive with some supervised methods. — [CIR survey](https://arxiv.org/pdf/2502.18495)
- **CIReVL** (Karthik, Roth, Mancini, Akata, ICLR 2024) works in three steps: caption the reference image, have an LLM rewrite the caption with the modification text, then retrieve with CLIP text→image. It is training-free and modular, and composing in language lets failures be inspected and corrected. — [CIReVL project page](https://eml-munich.de/publication/CIReVL)
- **TFCIR** (arXiv 2312.08924) has an LLM produce a pseudo target caption, then reranks the top candidates with local concept scores. It is competitive on CIRR, CIRCO and FashionIQ. — [arXiv 2312.08924](https://arxiv.org/html/2312.08924v1)
- **WeiMoCIR** (arXiv 2409.04918) uses a weighted average of the image-query and text-query embeddings, plus MLLM captions of database images. — [arXiv 2409.04918](https://arxiv.org/html/2409.04918v2)
- **MCoT-RE** (arXiv 2507.12819, 2025) has an MLLM produce two captions: a modification-focused one for **filtering** and a context-focused one for **re-ranking**. It reports up to +6.24% R@10 and +8.58% R@1 over prior training-free methods on FashionIQ and CIRR. — [MCoT-RE](https://arxiv.org/html/2507.12819v1)
- Caveat: arXiv 2606.07032 argues many ZS-CIR evaluations are not truly zero-shot because of pretraining overlap, so treat benchmark numbers loosely. — [arXiv 2606.07032](https://arxiv.org/pdf/2606.07032)

### Inferences
Recommended pipeline (maps directly onto MCoT-RE's filter-then-rerank structure):

1. **Offline:** for each corpus image, run Muse Spark once to get attribute JSON with a fixed per-domain schema. Example for watches: `{case_material, dial_colour, strap_type, …}`. Also compute the SAM 3.1 main-object mask, a Lab palette and a SigLIP/PE embedding. Store all of it.
2. **Query:** reference image + "change X to Y". Muse Spark produces the target attribute JSON (reference attributes with X replaced) and a target caption.
3. **Score candidates:**
   - Hard or soft filter on the varied attribute (it must match Y).
   - `α·cos(img_ref, img_cand)` on the preserved identity. Use a greyscale or masked embedding if the change is colour.
   - `β·cos(text_target, img_cand)`.
   - `γ·attribute-overlap` on the kept attributes. This is the WeiMoCIR-style weighted fusion.
4. **Rerank** the top ~20 with Muse Spark: "Does candidate keep A, B, C and have X=Y? Score 0–10 with reasons." This gives you explainability for the demo.

This baseline is cheap to evaluate by hand. Build 20–30 query pairs per domain and report hit@5.

### Gaps
- None of these papers cover UI screens, watches or interiors. FashionIQ (dress / shirt / toptee) is the only overlapping domain.
- No source compares VLM-JSON attribute filtering directly against embedding-only CIR.

## 4. Vector search for ~2k–20k images

### Takeaway
**At this scale you don't need a vector database.** Use **NumPy brute-force cosine over an `.npy` matrix plus a SQLite (or Parquet/JSON) metadata table**. If you want a library, choose **LanceDB** (embedded, file-based, SQL `where` pre-filtering). sqlite-vec is pre-v1 with thin filtering docs. pgvector needs a Postgres host. Chroma adds a server or persistence quirks for no gain at this size.

### Cited Findings
- LanceDB supports SQL-expression metadata filters with pre-filtering by default (before the vector search). Post-filtering is available via `prefilter=False`, and the Python API is `.search(...).where("...")`. — [LanceDB filtering docs](https://docs.lancedb.com/search/filtering); [LanceDB docs](https://lancedb.com/docs/search/filtering)
- sqlite-vec: "is a pre-v1, so expect breaking changes!" It installs with `pip install sqlite-vec` and supports "metadata, auxiliary, or partition key columns". IVF and DiskANN source files exist, but ANN usage is not documented in the README, and the GitHub Releases section appeared empty. — [sqlite-vec GitHub](https://github.com/asg017/sqlite-vec)
- **[UNVERIFIED]**
  - FAISS (`faiss-cpu`) `IndexFlatIP` is exact and trivially fast at 20k, but has no metadata filtering beyond ID selectors.
  - Chroma 1.x has a Rust core and supports `where` filters, embedded or server.
  - pgvector would need a hosted Postgres (Neon or Supabase free tiers) and adds network latency.

### Inferences
- 20k × 768 float32 is about 61 MB and one matmul takes milliseconds, so brute force is exact and faster to build than any DB.
- Ship the index files (`embeddings.npy`, `meta.sqlite` or `meta.parquet`, thumbnails) in the deploy image, or download them from HF Datasets or object storage at boot. Persistence is then a non-issue on ephemeral free tiers.
- Use LanceDB only if you want `where` filters on attribute JSON without writing pandas code. It is still just a directory of files.

### Gaps
- No live benchmarks of sqlite-vec vs LanceDB were found. The current LanceDB and Chroma version numbers were not fetched.

## 5. Front end for a draggable moodboard

### Takeaway
**Use React + `react-konva` (MIT) for the moodboard canvas.** tldraw is a heavier dependency, and production use needs a license key: without a paid commercial key it shows a watermark, and the trial lasts 100 days. A plain CSS grid plus `@dnd-kit` is the lowest-risk fallback if free-form canvas positioning isn't essential.

### Cited Findings
- **tldraw:**
  - "the SDK requires a license key to work in production". Without one it runs in development mode only.
  - License types: a trial (free 100 days, one per company or project), a commercial license (annual, removes the watermark, pricing via sales), and a hobby license (keeps the watermark, discretionary).
  - The license text forbids hiding or removing the watermark without a Business License.
  - Sources: [tldraw license key docs](https://tldraw.dev/sdk-features/license-key); [tldraw SDK License](https://tldraw.dev/legal/tldraw-license); [tldraw v3.0.0 release](https://tldraw.dev/releases/v3.0.0)
- **react-konva:** latest seen is v19.3.0, which requires React/ReactDOM ≥19.3.0. The notes recommend pinning `~19.2.7` if you're on React 19.2. Snyk lists it as MIT. — [react-konva v19.3.0 release](https://newreleases.io/project/github/konvajs/react-konva/release/v19.3.0); [Snyk react-konva](https://security.snyk.io/package/npm/react-konva)
- **[UNVERIFIED]** Konva core is MIT. Konva gives drag, `Transformer` (resize/rotate) and `stage.toDataURL()` export for "download moodboard as PNG" for free.

### Inferences
- A moodboard needs drag, resize, z-order and export. Konva covers all of these in about 150 lines. tldraw's whiteboard tooling (arrows, text, multiplayer) is unnecessary, and the watermark or 100-day trial is awkward for a public demo kept beyond the deadline.
- Match `react-konva` to the React version (`create-next-app` / Vite template) to avoid the 19.2 vs 19.3 peer-dependency trap.

### Gaps
- tldraw commercial pricing and whether a hobby license is granted for a public open-source demo: neither was listed publicly.

## 6. Deploy options and free tiers (public demo, public GitHub repo)

### Takeaway
**Front end: Vercel Hobby (or Netlify or Cloudflare Pages). Backend: Hugging Face Spaces (Docker or Gradio SDK, free CPU) or Modal ($30/month free credits).** Render's free tier (512 MB RAM, 0.1 CPU, ~1-minute cold start) is too small to load a PyTorch embedding model. Fly.io no longer has a meaningful free tier for new users.

### Cited Findings
- **Render free web services:**
  - 512 MB RAM and 0.1 CPU.
  - Spin down after 15 minutes idle, with ~1-minute spin-up. A Feb 2026 change also counts WebSocket messages as activity.
  - 750 free instance hours per workspace per month.
  - $7/mo for 512 MB, $25/mo for 2 GB.
  - Render's own docs say "Do not use free instances for production".
  - Sources: [Render free-tier article](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026.md); [Render changelog](https://render-www.onrender.com/changelog/free-web-services-now-remain-active-while-receiving-websocket-messages); [temps.sh Render pricing 2026](https://temps.sh/blog/render-pricing-2026)
- **Fly.io:** a 2026 comparison says it requires a credit card and has no free tier for new users. Another lists it as "Legacy Free". — [agentdeals Render alternatives](https://agentdeals.dev/alternative-to/render); [selfhost.dev](https://selfhost.dev/blog/best-render-alternatives-in-2026-compared/) (secondary, conflicting tone)
- **Modal:** the Starter plan is free with $30/month compute credits, 3 seats and 100 containers. — [Modal pricing](https://modal.com/pricing); [freetier.co](https://freetier.co/directory/products/modal)
- **[UNVERIFIED]**
  - HF Spaces free "CPU basic" is 2 vCPU / 16 GB RAM and sleeps after inactivity. It supports Docker Spaces and secrets, so the Meta API key can be stored as a Space secret.
  - Vercel Hobby is free for non-commercial use.

### Inferences
- Best fit: precompute all corpus embeddings, masks and attribute JSON offline on the Mac. Deploy FastAPI with a SigLIP-B or PE-Core-B model (~400 MB of weights) on an HF Space (16 GB RAM is ample) and the React front end on Vercel. Query-time embedding of one image or text on CPU is sub-second.
- Modal is the alternative if you want scale-to-zero with fast cold start. Mount the corpus via a Modal Volume.
- Free-tier cold starts (Render ~1 min, Spaces wake-up) will hurt a judged demo. Hit the endpoint before judging, or record a fallback video.
- Keep the Meta API key server-side only. A public repo must use `.env` + `.env.example` and platform secrets.

### Gaps
- HF Spaces hardware and sleep policy as of Oct 2026, and Vercel Hobby terms, were not verified live.
- Whether the Meta Model API allows calls from non-US server IPs (e.g. an HF Space in the EU/US) is unknown.

## 7. Recommended stack summary (opinionated, for this use case)

### Takeaway
Python 3.11/3.12 + FastAPI backend calling Meta Model API (`muse-spark-1.x`, `sam-3.1`) through the `openai` SDK. pycocotools/NumPy/scikit-learn/scikit-image for masks and Lab palettes. One generalist text-aligned embedder (SigLIP 2-B or PE-Core-B16, both Apache-2.0). NumPy brute-force (or LanceDB) over a precomputed corpus. React + react-konva moodboard on Vercel. Backend on an HF Space or Modal. Retrieval is a training-free CIR pipeline: VLM attribute JSON → filter → fused cosine → VLM rerank.

### Cited Findings
- Supporting evidence is cited in sections 0–6 above: Meta API compatibility, LookBench SigLIP2 > DINOv2, PE-Core Apache-2.0, the DINOv3 custom license, CIReVL/MCoT-RE, LanceDB filtering and sqlite-vec pre-v1, tldraw licensing, and Render limits and Modal credits.

### Inferences
Suggested 9-day order (inference):
- **D1:** API access check (India), SAM 3.1 mask format, embedder latency benchmark.
- **D2–3:** corpus ingest (≤5k images per domain is plenty) and offline features.
- **D4–5:** query pipeline + rerank.
- **D6–7:** Konva moodboard.
- **D8:** deploy.
- **D9:** eval set + demo video.

### Gaps
- The day-1 blockers are API access from India and the SAM 3.1 output format. Neither could be confirmed from public sources.
