# Stock / general image sources for a licensed retrieval corpus (Pexels, Unsplash, Openverse, Wikimedia Commons, Pixabay)

Research date: 2026-10-26. Quotes come from WebFetch extractions of the live pages. The fetch tool caps quote length, so some clauses are fragments. Before relying on any of them legally, re-open the page and copy the full sentence. Direct `curl` to pexels.com, unsplash.com and pixabay.com returned bot-protection stubs (5–8 KB pages), so all quotes from those sites come via WebFetch.

## API access: sign-up, keys, rate limits, production approval, cost

### Takeaway
All five are free. Pexels (200/hr, 20k/month by default) and Pixabay (100 per 60 s, cached 24 h) give a key instantly. Unsplash starts in demo mode at 50/hr and needs "Apply for Production" approval to reach 1,000/hr. Openverse works anonymously, but anonymous searches appear to cap at 240 results. Commons needs no key but requires a descriptive User-Agent; its 2026 rate limits are 10–200 req/min depending on how the client identifies itself.

### Cited Findings
- **Pexels: key.** "Anyone with a Pexels account can request an API key, which you will receive instantly." The key goes in an `Authorization` header. — [Pexels API docs](https://www.pexels.com/api/documentation/)
- **Pexels: limits.** "By default, the API is rate-limited to 200 requests per hour and 20,000 requests per month." Successful responses carry `X-Ratelimit-Limit/Remaining/Reset` headers; 429 responses do not. — [Pexels API docs](https://www.pexels.com/api/documentation/)
- **Pexels: higher limits and cost.** To ask for more, "please include examples, or be prepared to give a demo, that clearly shows your use of the API with attribution". "If you meet our API terms, you can get unlimited requests for free." Also: "All content is available free of charge." — [Pexels API docs](https://www.pexels.com/api/documentation/)
- **Unsplash: limits.** New apps start in demo mode, "rate-limited to 50 requests per hour". Approved production apps get 1,000 requests per hour. Only JSON calls to api.unsplash.com count; image requests to images.unsplash.com do not. To move up, use "Apply for Production" on the apps page; for more than 1,000/hr, contact partnerships@unsplash.com. The docs page does not mention pricing. — [Unsplash API docs](https://unsplash.com/documentation)
- **Unsplash: quotas and fees.** "You will not attempt to exceed or circumvent automated use or quota restrictions." Unsplash may set quotas and may charge a technology fee to businesses that use the API heavily. — [Unsplash API Terms §12](https://unsplash.com/api-terms)
- **Pixabay: limits and caching.** "you can make up to 100 requests per 60 seconds", tied to the API key rather than the IP. "requests must be cached for 24 hours." "By default, the API is limited to return a maximum of 500 images per query." — [Pixabay API docs](https://pixabay.com/api/docs/)
- **Openverse: registration.** `POST /v1/auth_tokens/register/` with `name`, `description` and `email` returns a `client_id` and `client_secret`, which cannot be retrieved later. The token comes from `/v1/auth_tokens/token/` (client-credentials grant). "Until you do that [verify email], the application will be subject to the same rate limits as an anonymous user." — [Openverse API schema](https://api.openverse.org/v1/schema/)
- **Openverse: tiers.** There are three tiers: `standard` ("The default rate limit that anyone is able to unlock simply by authenticating"), `enhanced` (granted selectively) and `exempt` (internal). The docs give no numbers. — [Openverse docs: Authentication and Throttling](https://docs.openverse.org/api/reference/authentication_and_throttling.html)
- **Openverse: unverified numbers.** A community MCP package lists anonymous access at 100/day and 5/hr, and authenticated access at 10,000/day and 100/min. These are third-party figures. — [mcp-openverse (npm)](https://www.npmjs.com/package/mcp-openverse)
- **Openverse: page_size history.** A 2022 post says anonymous requests with `page_size` > 20 began returning 401. — [Openverse make.wordpress.org 2022](https://make.wordpress.org/openverse/2022/08/11/openverse-api-results-constrained-to-20-pages/); [mitigating out-of-terms usage](https://make.wordpress.org/openverse/2022/06/17/mitigating-out-of-terms-api-usage/)
- **Openverse: depth.** The schema says only "the most relevant or the most recent several thousand records can be viewed" and that callers should not request pages beyond `page_count`. — [Openverse API schema](https://api.openverse.org/v1/schema/)
- **Openverse: observed cap.** Two anonymous searches I ran each returned `result_count: 240` ("wristwatch dial" with page_size 5 gave page_count 48; "mobile app UI" with page_size 10 gave page_count 24). — direct calls to [api.openverse.org/v1/images](https://api.openverse.org/v1/images/?q=wristwatch%20dial&page_size=5)
- **Wikimedia: rate limits (new in 2026).** Per minute:
  - IP-only anonymous clients: 10 req/min
  - Unauthenticated bots with a "compliant User-Agent": 200 req/min
  - New or low-edit authenticated users: 200 req/min
  - Established editors: 2,000 req/min
  - Bot-flagged accounts: exempt

  The page says "The rate limits described on this page are new in 2026 and are subject to experimentation and change." It was last edited 15 October 2026. — [Wikimedia APIs/Rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits)
- **Wikimedia: request etiquette.** "Making your requests in series rather than in parallel". Use `maxlag` for non-interactive jobs. "API requests to Wikimedia wikis must include a meaningful User-Agent header." — [MediaWiki API:Etiquette](https://www.mediawiki.org/wiki/API:Etiquette)
- **Wikimedia: User-Agent policy (last edited 27 March 2026).**
  - Format: "<client name>/<version> (<contact information>) <library/framework name>/<version>".
  - "Do not use generic agents such as "curl", "lwp", "Python-urllib"".
  - "Do not copy a browser's user agent for your bot."
  - Requests without one may get HTTP 403 or be "blocked without notice".

  — [WMF User-Agent Policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy)

### Inferences
- For a hackathon demo, Unsplash's 50/hr demo tier is the tightest bottleneck. Production approval is a manual review, so it may not arrive in time.
- Openverse anonymous access is fine for spot checks. For corpus building, register and verify an email, because anonymous depth seems capped at about 240 results per query.

### Gaps
- No official current Openverse rate-limit numbers for the anonymous or standard tiers. The schema delegates them to a `#tag/auth` section that did not render.
- No published turnaround time for Unsplash production approval.
- The Pexels API Terms URL (`/api/terms/`) returned 404. The API rules found sit in the docs "Guidelines" section and the site ToS.

## Display rules: hotlinking vs caching, attribution format, anti-competing / "replicate" clauses

### Takeaway
- **Unsplash** forbids self-hosting for display (hotlinking is mandatory), requires a download-event ping, and bans replicating its core experience or building competitive products.
- **Pixabay** is the opposite: images must be downloaded to your own server, and "permanent hotlinking" is banned.
- **Pexels** states no hotlinking rule. It requires a prominent Pexels link plus photographer credit, and bans replicating core functionality.
- **Commons** discourages hotlinking (but allows it) and requires a per-file attribution that follows the file's license.
- **Openverse** bans scraping and requires CC attribution.

### Cited Findings
- **Pexels: attribution.** "Always credit our photographers when possible." Show a prominent link to Pexels (text or logo) wherever API results appear. The example credit is "Photo by John Doe on Pexels", linked to the photo page. — [Pexels API docs](https://www.pexels.com/api/documentation/)
- **Pexels: replication and abuse.** "You may not copy or replicate core functionality of Pexels." Abuse, including getting around the rate limit, can end API access. The docs state no hotlinking or caching rule. — [Pexels API docs](https://www.pexels.com/api/documentation/)
- **Pexels ToS ("Last updated: October 20th, 2026"), §8.** Prohibits:
  - "use or compile any Content to replicate a similar or competing service to the Service, … or copy the look or feel or the Service"
  - "Bulk, large-scale or systematic copying of Content is strictly prohibited unless explicit permission has been granted by us."

  — [Pexels Terms of Service](https://www.pexels.com/terms-of-service/)
- **Pexels License (undated, "© 2026").** "Attribution is not required." Prohibits:
  - "Don't redistribute or sell the photos and videos on other stock photo or wallpaper platforms."
  - "Don't imply endorsement of your product by people or brands on the imagery."

  — [Pexels License](https://www.pexels.com/license/)
- **Unsplash: hotlinking (§6).** "you must directly use or embed the related image URLs returned by the API in your Developer Apps". Failing to do so is a material breach. — [Unsplash API Terms](https://unsplash.com/api-terms)
- **Unsplash: guidelines (dated July 27, 2026).**
  - "All API uses must use the hotlinked image URLs returned by the API under the `photo.urls` properties."
  - "you must send a request to the download endpoint returned under the `photo.links.download_location` property."
  - "your application must attribute Unsplash, the Unsplash photographer, and contain a link back to their Unsplash profile."
  - Links must use "?utm_source=your_app_name&utm_medium=referral".
  - "You cannot replicate the core user experience of Unsplash (unofficial clients, wallpaper applications, etc.)."

  — [Unsplash API Guidelines](https://help.unsplash.com/en/articles/2511245-unsplash-api-guidelines)
- **Unsplash: competing products and usage data.** §6(b) prohibits using the API to "create, market, or distribute any product or service that is competitive with Unsplash's products". Image-interaction data must not be sold or disclosed, or used to build competing products. Attribution is required each time an image is displayed (§9). The API Terms page shows no last-updated date. — [Unsplash API Terms](https://unsplash.com/api-terms)
- **Unsplash License.** Not permitted: "Compiling images from Unsplash to replicate a similar or competing service." — [Unsplash License](https://unsplash.com/license)
- **Pixabay: display rules.**
  - "permanent hotlinking of images (using Pixabay URLs in your app) is not allowed". Temporary display of the returned URLs is allowed.
  - "show your users where the images and videos are from, whenever search results are displayed."
  - "Systematic mass downloads are not allowed."

  — [Pixabay API docs](https://pixabay.com/api/docs/)
- **Pixabay ToS ("Last updated: 20 October, 2026"), §8.** Prohibits "use or compile any Content to replicate a similar or competing service to the Service" and "Bulk, large-scale or systematic copying of Content". — [Pixabay Terms](https://pixabay.com/service/terms/)
- **Openverse ToS ("Effective as of 5 May 2022").**
  - "You must not scrape the content in the Openverse catalog"
  - "You must adhere to all rate limits, registration requirements…"
  - Users must provide "proper attribution to CC-licensed works" and respect the terms of the platforms hosting them.

  — [Openverse Terms of Service](https://docs.openverse.org/terms_of_service.html)
- **Commons: hotlinking.** "Directly using a Commons file via embedding its URL ("hotlinking") is also possible, but is not recommended". Hotlinking does not remove license duties. — [Commons:Reusing content outside Wikimedia](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia) (last edited 11 Aug 2026)
- **Commons: attribution.** Credit the creator, and "If the copyright holder … has specified how, be sure to follow this". Link to the license, plus the source where the file came from elsewhere. — [Commons:Reusing content outside Wikimedia](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia)

### Inferences
- A "design-reference retrieval" app that searches, browses and saves boards is arguably close to Unsplash's "core user experience" and to the Pexels/Pixabay "similar or competing service" language. Keep the corpus small and purpose-specific (curation and analysis), and avoid presenting the app as a general stock-photo browser.
- Unsplash's hotlinking requirement conflicts with storing local copies for display. Embeddings can be computed from a fetched image (which counts as a "download" event to report), but display should still use `photo.urls`.
- Pixabay is the only source that explicitly requires self-hosting (cache 24 h, no permanent hotlinking).

### Gaps
- Whether Pexels permits storing copies on your own server: the API docs are silent. The Pexels License allows downloading and use, but the ToS bans "systematic copying" without permission.
- Unsplash: no explicit rule on caching thumbnails.

## AI processing: embeddings, segmentation, captioning, derived features, training

### Takeaway
- **Unsplash** is the most restrictive. The API Terms route "any machine learning and/or artificial intelligence purposes" with API content to unsplash.com/data, so embeddings and captioning of API content are not clearly permitted without contacting Unsplash.
- **Pexels and Pixabay** ToS (both updated 20 Oct 2026) ban scraping and automated collection "for all unauthorised purposes, including without limitation for machine learning purposes". ML use of API results is a grey zone.
- **CC content via Commons/Openverse** has no platform-level AI ban. The per-file CC license governs.

### Cited Findings
- **Unsplash API Terms §12 (undated).** "In the event you desire to use the Content sourced from the API in connection with any machine learning and/or artificial intelligence purposes" you should visit unsplash.com/data. The same referral covers technologies for identifying natural persons. (Fetched text was truncated; re-copy the full sentence.) — [Unsplash API Terms](https://unsplash.com/api-terms)
- **Unsplash /data.**
  - "Train and test models using the largest collaborative image dataset ever openly shared."
  - The Lite tier is "Free for commercial and non-commercial usage": 25,000 images, about 1.5 GB, on GitHub.
  - The Full tier (4.8M+ images) is available on request.
  - The page shows no date or pricing.

  — [Unsplash Dataset](https://unsplash.com/data)
- **Pexels ToS §8 (last updated October 20th, 2026).** "Data mining, extraction, scraping and the use of programs or robots for automatic data collection and/or extraction of digital data on the Service and/or the content available therein is strictly prohibited for all unauthorised purposes, including without limitation for machine learning purposes." This is reassembled from consecutive fetched fragments; verify against the page. — [Pexels Terms of Service](https://www.pexels.com/terms-of-service/)
- **Pexels ToS §7A (Pexels' own AI use).** Pexels states that it and its partners may use contributor content "including through the use of machine learning technology". Contributors can opt out "of future AI training". — [Pexels Terms of Service](https://www.pexels.com/terms-of-service/)
- **Pexels License.** The license page does not mention AI or ML. — [Pexels License](https://www.pexels.com/license/)
- **Pixabay ToS (last updated 20 October 2026).** It carries the same §8 "Data mining, extraction, scraping and the use of programs or robots for automatic data collection" prohibition and the same §7A ML and "opting out of future AI training" language. The API docs page has no AI clause. — [Pixabay Terms](https://pixabay.com/service/terms/); [Pixabay API docs](https://pixabay.com/api/docs/)
- **Unsplash License.** The license page does not mention AI or ML. — [Unsplash License](https://unsplash.com/license)
- **Openverse ToS.** It does not mention AI or ML. The licensing caveat: Openverse "does not verify its licensing status or make any representations or warranties" and "You are responsible for independently verifying whether you have the right to use the content". — [Openverse ToS](https://docs.openverse.org/terms_of_service.html)

### Inferences
- **Commons/Openverse.** Running inference (CLIP embeddings, segmentation, captioning) on CC-licensed images and storing vectors is generally compatible with CC licenses. Embeddings are not a reproduction for display. This is my reading, not a quoted rule.
- **CC-ND and CC-NC.** Exclude CC-ND if you plan to show crops or segment masks as derivatives. Exclude CC-NC if the product is commercial.
- **Pexels/Pixabay API use is "authorised" access**, so the scraping clause arguably does not apply. But "Bulk, large-scale or systematic copying" without permission does, and building a corpus is systematic. The safest path for a hackathon is a small set fetched through the API, with attribution, plus a written permission request.
- **Unsplash.** Treat embedding Unsplash API images as needing Unsplash's sign-off, or use the Unsplash Lite Dataset, which is explicitly offered for training and testing (check the dataset's own license on GitHub).

### Gaps
- The Unsplash Lite dataset's own license terms (GitHub) were not fetched.
- The Wikimedia Foundation Terms of Use were not fetched for any AI or ML clause.
- None of the API terms explicitly distinguish inference (embeddings) from training.

## Per-image license and provenance metadata returned by the APIs

### Takeaway
Each API returns enough metadata to store provenance without inventing it:
- **Openverse** is richest: `creator`, `license`, `license_version`, `license_url`, `foreign_landing_url`, and a ready-made `attribution` string.
- **Commons** `extmetadata` gives `Artist`, `LicenseShortName`, `LicenseUrl`, `AttributionRequired` and `UsageTerms`.
- **Pexels, Unsplash and Pixabay** return photographer name and URLs. They return no per-image license field, because every image is under the site license.

### Cited Findings
- **Pexels Photo object.** `photographer`, `photographer_url`, `url` ("The Pexels URL where the photo is located"), `alt`, `id`, `width`, `height`, `avg_color`, `src`. Search responses include `total_results`. — [Pexels API docs](https://www.pexels.com/api/documentation/)
- **Pexels License.** "All photos and videos on Pexels can be downloaded and used for free." "You can modify the photos and videos from Pexels." "Don't sell unaltered copies of a photo or video". — [Pexels License](https://www.pexels.com/license/)
- **Unsplash search response.**
  - Top level: `total`, `total_pages`.
  - Per photo: `description`, `alt_description`, `user.name`, `user.username`, `links.html`, `urls.*`, `links.download_location`.

  — [Unsplash API docs](https://unsplash.com/documentation); [Unsplash API Guidelines](https://help.unsplash.com/en/articles/2511245-unsplash-api-guidelines)
- **Unsplash License.** "irrevocable, nonexclusive, worldwide copyright license to download, copy, modify, distribute". "Images cannot be sold without significant modification." — [Unsplash License](https://unsplash.com/license)
- **Unsplash+ results.** Some search results are Unsplash+ (premium). In a "chronograph watch" web search sample, 5 of 20 visible results were Unsplash+. — [Unsplash search page](https://unsplash.com/s/photos/chronograph-watch)
- **Pixabay fields.** `user`, `user_id`, `pageURL`, `tags`, `total`, `totalHits`. — [Pixabay API docs](https://pixabay.com/api/docs/)
- **Openverse fields.** `creator`, `creator_url`, `license`, `license_version`, `license_url`, `foreign_landing_url`, `attribution` ("Legally valid attribution for the item, in plain-text English"), `provider`, `source`, `url`. — [Openverse API schema](https://api.openverse.org/v1/schema/)
- **Openverse sample.** The "wristwatch dial" results mixed BY, BY-SA and BY-NC licenses, mostly from the Flickr provider. Example: "Huguenin Vintage Watch - patina on dial", GuySie, CC BY-SA 2.0. — [Openverse API](https://api.openverse.org/v1/images/?q=wristwatch%20dial&page_size=5)
- **Commons imageinfo (live call).** `prop=imageinfo&iiprop=url|extmetadata|size` returned:
  - `url`, `thumburl`, `descriptionurl`
  - `Artist`: an HTML link to User:Pittigrilli
  - `Credit`: "Own work"
  - `LicenseShortName`: "CC BY-SA 4.0"
  - `LicenseUrl`: https://creativecommons.org/licenses/by-sa/4.0
  - `AttributionRequired`: true
  - `UsageTerms`, `DateTimeOriginal`, `ImageDescription`

  The sample file was "File:Detailed view of dial of chronograph watch.jpg". — [Commons API](https://commons.wikimedia.org/w/api.php?action=query&titles=File:Detailed%20view%20of%20dial%20of%20chronograph%20watch.jpg&prop=imageinfo&iiprop=url|extmetadata|size&format=json)
- **Commons: multiple licenses and other restrictions.** "If the file is available under multiple licenses, you can use any of them." Other restrictions (trademarks, personality rights) may apply. "the Wikimedia Foundation does not provide any warranty regarding the copyright status or correctness of licensing terms." — [Commons:Reusing content outside Wikimedia](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia)

### Inferences
- **Suggested provenance schema:** `source`, `source_id`, `landing_url`, `creator_name`, `creator_url`, `license_code`, `license_url`, `attribution_text`, `fetched_at`, `api_terms_version_date`.
- **Pexels/Unsplash/Pixabay:** set `license` as a constant (for example "Pexels License"), since the API returns no per-image license field.
- **Commons `Artist`** is HTML and must be sanitized before display.
- **Unsplash+:** filter out premium items (`premium`/`plus` flags) before ingest. Field names not verified.
- **Brand logos:** watch and fashion images often show trademarks. The Pexels/Commons warnings about implied endorsement and trademarks apply when brand logos are visible.

### Gaps
- The exact Unsplash JSON flag for Unsplash+ / premium was not verified.

## Coverage for the four domains (watches, fashion, interiors, UI screens)

### Takeaway
- **Commons** has strong, well-captioned watch close-ups (361–876 hits) and huge interior and dress counts. Many interior and dress hits are museum or historical items rather than contemporary design.
- **Pexels and Unsplash** have the most modern, aesthetic product, fashion and interior photography. Pexels counts are inflated by fuzzy matching.
- **UI/app screens** are poorly covered everywhere. Openverse/Commons hits are mostly photos of devices or open-source tool screenshots, not design-quality UI.

### Cited Findings
- **Commons file-namespace search counts (live API, srnamespace=6):**

| Query | Hits | What the top results are |
|---|---|---|
| "wristwatch dial" | 361 | Seiko and Rolex Daytona dial close-ups |
| "chronograph watch" | 876 | e.g. "Guinand 60.50 … Valjoux 7750" |
| "linen dress" | 35,792 | Top hits are Sybil Connolly museum dresses and an ancient Egyptian linen dress |
| "streetwear" | 808 | |
| "living room interior" | 57,477 | Top hits include paintings and museum rooms |
| "mid-century sofa" | 1,457 | Top hits are 19th-century museum sofas, so the match is poor |
| "mobile app UI" | 1,915 | Icons, the Commons app screenshot, PDFs |
| "dashboard UI" | 1,972 | Ceph, Virtualmin and Bareos admin screenshots |

  — [Commons search API](https://commons.wikimedia.org/w/api.php?action=query&list=search&srsearch=chronograph%20watch&srnamespace=6&format=json)
- **Openverse (anonymous):** both "wristwatch dial" and "mobile app UI" returned `result_count` 240, which looks capped. Of the top 10 "mobile app UI" results, about one ("iPhone Health Apps: UIs gone wrong") was clearly UI screens. Most were Flickr phone photos titled IMG_03xx, all CC BY 2.0. — [Openverse API](https://api.openverse.org/v1/images/?q=mobile%20app%20UI&page_size=10)
- **Unsplash web search, "chronograph watch":** about "1.7k" photos. 5 of the 20 visible results were Unsplash+ premium. — [Unsplash search](https://unsplash.com/s/photos/chronograph-watch)
- **Pexels web search, "chronograph watch":** "85.4K" photos. That is an abbreviated figure and almost certainly a broad semantic match, not exact. — [Pexels search](https://www.pexels.com/search/chronograph%20watch/)

### Inferences
- **Watches:** Commons gives accurate, captioned macro shots. Pexels and Unsplash give lifestyle and editorial watch shots.
- **Fashion:** Pexels and Unsplash are likely strongest for contemporary streetwear and editorial work. Commons skews toward museum costume and runway photos with personality-rights caveats.
- **Interiors:** Pexels and Unsplash are likely strongest for contemporary interiors. Use Commons for named designer furniture with clear captions.
- **UI screens:** none of these sources is a good corpus. Consider generating your own screenshots of open-source apps (with license checks), or a dedicated UI dataset, which is outside this note's scope.

### Gaps
- No API-key counts for Pexels, Unsplash or Pixabay across the eight queries; no keys were available, and their web pages are bot-protected. Only "chronograph watch" was checked via the web UI.
- No authenticated Openverse counts. The anonymous count of 240 is a cap, not the true total.
- No visual quality assessment of results. Domain-fit judgments rest on titles and captions.
- Relevance to the Meta hackathon rules (no unlicensed assets, credit sources, no scraping): using official APIs with keys and attribution is consistent with "no scraping". Openverse, Pexels and Pixabay also forbid scraping and systematic mass downloading in their own terms. I did not fetch the hackathon rules text itself.
