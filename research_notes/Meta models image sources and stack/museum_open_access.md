# Museum Open-Access Image APIs as Sources for a Licensed Design-Reference Corpus

Researched 2026-10-26. Sources checked: The Met, Smithsonian Open Access (including Cooper Hewitt / CHNDM), Rijksmuseum, V&A, Art Institute of Chicago (AIC), Europeana. Live API queries were run on 2026-10-26, and all counts below come from those queries. Keyword-search counts are noisy upper bounds and are labelled as estimates.

Several primary policy pages could not be fetched by automated tools on the research date: metmuseum.org returned HTTP 429, si.edu returned 403, artic.edu and api.artic.edu/docs returned a Cloudflare 403 challenge, pro.europeana.eu returned 403, and the edan.si.edu apidocs page is rendered by JavaScript. For these sites the findings rely on the official GitHub repos, live API responses and search snippets. The Gaps sections say which is which.

## Licensing: CC0 status, how open-access images are flagged, attribution, and storage/display/AI restrictions

### Takeaway
The Met, Smithsonian (including Cooper Hewitt), AIC and most of the Rijksmuseum release public-domain images under CC0 and flag each object or image individually. The V&A does not: its API terms allow only non-commercial use, ban keeping API content longer than four weeks and require images to be hotlinked. That makes it unsuitable for a stored corpus. Europeana is an aggregator, so its licensing varies per record and must be filtered for open reuse.

### Cited Findings
**The Met**
- The Met's Open Access CSV covers 470,000+ artworks. The Met "has waived all copyright and related or neighboring rights to this dataset using Creative Commons Zero", for "unrestricted commercial and noncommercial use". — [metmuseum/openaccess README](https://github.com/metmuseum/openaccess)
- The CSV does not include images. Covered artworks are marked with the CC0 icon on the Met website. — [metmuseum/openaccess README](https://github.com/metmuseum/openaccess)
- Attribution is not required but is requested: "Please consider attributing or citing The Metropolitan Museum of Art's CC0 select datasets". The README also says "Do not mislead others or misrepresent the datasets". — [metmuseum/openaccess README](https://github.com/metmuseum/openaccess)
- The API docs describe the API as giving access "to all of The Met's Open Access data and to corresponding high resolution images (JPEG format) that are in the public domain". — [Met Collection API docs](https://metmuseum.github.io/)
- Per-object flag, verified live: each object has `isPublicDomain: true/false`. When it is false, `primaryImage` and `primaryImageSmall` are empty strings, as for object 1 and object 195588. Note that `hasImages=true` in search does not mean an open-access image exists. — live API, [objects/194074](https://collectionapi.metmuseum.org/public/collection/v1/objects/194074)

**Smithsonian / Cooper Hewitt**
- The Smithsonian Open Access GitHub repo is CC0-1.0 licensed, holds "Over 11 million metadata records", and lists CHNDM (Cooper Hewitt, Smithsonian Design Museum) as one owning unit. — [Smithsonian/OpenAccess](https://github.com/Smithsonian/OpenAccess)
- Per-image flag, verified in the bulk data: `content.descriptiveNonRepeating.online_media.media[].usage.access`, with the value "CC0". All 2,670 media items across 1,800 sampled CHNDM records had `access: "CC0"`. — [SI S3 CHNDM shards](https://smithsonian-open-access.s3-us-west-2.amazonaws.com/metadata/edan/chndm/index.txt)
- The Smithsonian says media URLs are included only for public-domain objects. Objects with possible copyright or other limits get CC0 metadata but no media file. — search snippet of [si.edu/openaccess/devtools](https://www.si.edu/openaccess/devtools); the page itself returned 403 to direct fetch.
- Cooper Hewitt's API home says: "Use our collection of CC0 objects to remix and get creative with a completely open license." — [apidocs.cooperhewitt.org](https://apidocs.cooperhewitt.org/api-home)

**Rijksmuseum**
- Rijksmuseum data can be used commercially without permission. Much of the material carries Public Domain or CC0 marks. Where copyright applies, CC BY 4.0 is shown and the Rijksmuseum must be credited. Some material, such as photos of in-copyright objects, is not free, and the rights holder is named in the copyright notice. Credit is "kindly ask[ed]... even if this is not required". — [Rijksmuseum Information and Data Policy](https://data.rijksmuseum.nl/policy/)
- History: CC-BY release in 2011. In 2013 the museum "placed the majority of its digitised museum objects in the public domain". It currently offers 800,000+ object records and high-resolution photos of 600,000 objects. — [data.rijksmuseum.nl](https://data.rijksmuseum.nl/)

**V&A**
- Section 9.1 of the V&A terms allows the APIs to be used "for non-commercial personal and educational purposes". Commercial use requires contacting vaimages@vam.ac.uk. — [V&A websites terms and conditions](https://www.vam.ac.uk/info/va-websites-terms-conditions/), last updated September 2026
- Section 9.3: "You will not cache or store any content returned by the V&A API for more than four weeks. If you display images in your website or application you must use the image url returned by our API rather than create a copy on your local web server." The API may not be sold or provided to third parties. — [V&A terms](https://www.vam.ac.uk/info/va-websites-terms-conditions/)
- Required credit for V&A-owned content: "© Victoria and Albert Museum, London". The V&A brand may not suggest endorsement. — [V&A terms §5](https://www.vam.ac.uk/info/va-websites-terms-conditions/)

**Art Institute of Chicago**
- AIC offers "free, unrestricted use" of 50,000+ public-domain images under CC0. Object information is also CC0. Aggregators say artwork descriptions are CC BY 4.0. — search snippet of [artic.edu open access images](https://www.artic.edu/open-access/open-access-images); the page returned 403 to direct fetch, so the description licence is unverified.
- Per-object flag, verified live: the `is_public_domain` boolean, plus `image_id`. A combined filter worked in an Elasticsearch POST query to `/api/v1/artworks/search`. — live API

**Europeana**
- Europeana aggregates many institutions, so rights vary by record. The `reusability=open` search parameter, used in the queries below, limits results to open licences. — live API

### Inferences
- For the hackathon rules (no assets without rights, credits required, no scraping), the safest sources are the Met (`isPublicDomain=true`), Smithsonian/Cooper Hewitt (`usage.access=="CC0"`), AIC (`is_public_domain=true`) and Rijksmuseum CC0/PD items. CC0 needs no credit, but a credits page listing museum, object title, accession number and object URL meets the "require credits" rule and every museum's request.
- The V&A should be excluded from a stored or processed corpus. Its four-week cache limit, ban on local copies and non-commercial-only terms conflict with building a corpus. At most it could be hotlinked live, for a non-commercial demo only.
- None of the CC0 sources reviewed says anything specific about AI/ML. CC0 waives all rights, so ML processing is allowed in principle. The Met's "do not misrepresent" guideline and the Rijksmuseum's no-endorsement wording mean outputs should not be presented as museum-endorsed.

### Gaps
- The Met's Open Access policy page (metmuseum.org/policies/image-resources) returned HTTP 429, so its current wording and date were not checked. Licence findings rely on the GitHub README and API docs.
- No museum page reviewed had an explicit AI/ML-training clause. The V&A terms were searched for "artificial intelligence", "machine learning", "data mining" and "scrap" and none matched. The other sites could not be text-searched.
- Europeana's API terms page (pro.europeana.eu) returned 403, so its attribution and usage terms are not confirmed.
- The AIC descriptions licence (CC BY) comes only from aggregators.

## API access: keys, rate limits, endpoints, image URL fields and sizes, bulk downloads

### Takeaway
No key is needed for the Met, Rijksmuseum (new data services), V&A or AIC. Smithsonian needs a free api.data.gov key: 1,000 requests per hour, while DEMO_KEY is far lower and was exhausted during testing. The Met retired its old search endpoint on 2026-10-01. Bulk downloads exist and are the preferred route: the Met's CSV via Git LFS (metadata only), Smithsonian line-delimited JSON on public S3, and Rijksmuseum data dumps.

### Cited Findings
**The Met** (`https://collectionapi.metmuseum.org/public/collection/`)
- No key or registration. "Please limit request rate to 80 requests per second." — [Met API docs](https://metmuseum.github.io/)
- Breaking change: `/v1/search` was retired on 2026-10-01. The live response says it was Solr-backed and returned every matching ID in one response, and points callers to `/public/collection/v1.1/search`, which is Elastic-backed and paged by `offset` (default 0) and `limit` (default 100, maximum 500). The v1.1 endpoint was announced 2026-09-04. — [Met API docs "Latest Updates"](https://metmuseum.github.io/); live API response
- Other endpoints: `/v1/objects` lists all IDs (live total 503,012, optional `departmentIds`), `/v1/objects/{id}` returns object detail, and `/v1/departments` lists departments (department 8 is The Costume Institute, with 31,898 object IDs). — live API
- Image fields: `primaryImage` (original, e.g. `images.metmuseum.org/CRDImages/es/original/...jpg`), `primaryImageSmall` (`.../web-large/...`) and `additionalImages[]` (originals). — live API, [objects/194074](https://collectionapi.metmuseum.org/public/collection/v1/objects/194074)
- Bulk: `MetObjects.csv` in GitHub, stored in Git LFS (`git lfs clone`), includes metadata only and no images. — [metmuseum/openaccess](https://github.com/metmuseum/openaccess)
- Gotcha observed: v1.1 ignored an `isPublicDomain=true` parameter, returning identical totals. Public-domain status has to be checked per object.

**Smithsonian Open Access** (`https://api.si.edu/openaccess/api/v1.0/`)
- The key comes from api.data.gov. The default limit is "1,000 requests per hour" per key across all api.data.gov services, and going over blocks the key for an hour. DEMO_KEY allows 30 requests per IP per hour and 50 per IP per day. — [api.data.gov developer manual](https://api.data.gov/docs/developer-manual/)
- Observed: after about 22 calls with DEMO_KEY the API returned HTTP 429 `OVER_RATE_LIMIT`, with `x-ratelimit-limit: 10` and `retry-after: 32278` seconds. The current effective DEMO_KEY limit may be stricter than documented. — live API
- The search endpoint, `/search?q=...&rows=&start=&api_key=`, takes Solr-style queries such as `online_media_type:Images` and `unit_code:CHNDM`. — live API
- Image fields, verified in the bulk JSON: `media[].content` and `thumbnail` are `https://ids.si.edu/ids/deliveryService?id=...`, and `media[].resources[]` holds labelled renditions such as "High-resolution JPEG" (`ids.si.edu/ids/download?id=....jpg`, e.g. 4552x6904) and "Screen Image". `width`, `height` and alt text (`altTextAccessibility`) are included. — [SI S3 CHNDM data](https://smithsonian-open-access.s3-us-west-2.amazonaws.com/metadata/edan/chndm/index.txt)
- Bulk: the S3 bucket `smithsonian-open-access` (us-west-2) holds line-delimited JSON split by unit, with each unit in 256 hash-prefixed shards. CHNDM shards are about 0.8–1.0 MB each. The GitHub repo is now marked "Public archive". — [Smithsonian/OpenAccess](https://github.com/Smithsonian/OpenAccess)

**Cooper Hewitt**
- The old REST API is gone. `collection.cooperhewitt.org/api/` returns 301 to `si.edu/collections/cooper-hewitt`, and `api.collection.cooperhewitt.org/rest/` returns 404. Cooper Hewitt now advertises a GraphQL API at apidocs.cooperhewitt.org. — live HTTP checks; [apidocs.cooperhewitt.org](https://apidocs.cooperhewitt.org/api-home)
- The simplest licensed route to Cooper Hewitt images is Smithsonian Open Access (`unit_code:CHNDM`, or the S3 `chndm/` shards). — [Smithsonian/OpenAccess](https://github.com/Smithsonian/OpenAccess)

**Rijksmuseum**
- New search API: `https://data.rijksmuseum.nl/search/collection` with parameters including `type`, `title`, `creator`, `creationDate`, `material`, `description`, `imageAvailable=true` and `pageToken`. It accepts Dutch or English terms. No key was needed. — [Rijksmuseum search docs](https://data.rijksmuseum.nl/docs/search); live API
- It returns Linked Art `OrderedCollectionPage` JSON-LD containing only object IDs (`id.rijksmuseum.nl/...`) and `totalItems`. Details and images need follow-up dereferencing. — live API
- Data is offered "through APIs and as a download" (data dumps), modelled in EDM and Linked Art. The service is "a work in progress", so structure may change. — [data.rijksmuseum.nl](https://data.rijksmuseum.nl/)

**V&A** (`https://api.vam.ac.uk/v2/objects/search`)
- No key was needed in testing, but the V&A reserves the right to require keys in future. Section 9.2 asks callers not to make an unreasonable number of calls and states a request rate of "no more frequently than one request per second"; the snippet also mentions a daily call cap whose figure was cut off. — [V&A terms](https://www.vam.ac.uk/info/va-websites-terms-conditions/)
- Search records include `_images._iiif_image_base_url` (e.g. `https://framemark.vam.ac.uk/collections/2019LM6177/`), `_primary_thumbnail` (`.../full/!100,100/0/default.jpg`), `_iiif_presentation_url` and `imageResolution`. — live API
- For bulk export, the V&A asks users to file an issue on its GitHub instead of using the API. — [V&A API guide](https://developers.vam.ac.uk/guide/v2/welcome.html)

**AIC** (`https://api.artic.edu/api/v1/`)
- No key. POST JSON Elasticsearch queries to `/artworks/search` work and return `pagination.total`. An `AIC-User-Agent` header is requested. — live API
- GET requests to api.artic.edu from the research sandbox returned a Cloudflare "Just a moment..." challenge page, while POST requests succeeded. — live API
- Aggregators report a rate limit of 60 requests per minute per IP for anonymous use, plus nightly JSON data dumps; one aggregator says there is no hard limit. — [freeapihub / jentic listings via search](https://freeapihub.com/apis/art-institute-chicago)

**Europeana** (`https://api.europeana.eu/record/v2/search.json`)
- The public demo key `wskey=api2demo` worked. The parameters `reusability=open`, `media=true` and `qf=TYPE:IMAGE` returned counts. — live API

### Inferences
- For hackathon "no scraping" compliance, use the official bulk channels: the Met CSV filtered on Is Public Domain and then the object API for image URLs, Smithsonian S3 JSON, and Rijksmuseum dumps. Download images only from the documented image URL fields, at polite rates.
- Ignore older tutorials and code that call Met `/v1/search` (dead since 2026-10-01), the Cooper Hewitt REST API (dead) or the old key-based Rijksmuseum API (superseded by data.rijksmuseum.nl). Most pre-2026 sample code is affected.

### Gaps
- The Met CSV column list, including whether it has an image-URL column, was not checked beyond the README statement that images are not included. Its size was not measured.
- Smithsonian documented per-key limits beyond the api.data.gov default were not confirmed, because the edan.si.edu docs need JavaScript.
- The AIC rate limit and IIIF size guidance could not be confirmed from primary docs (403).
- The V&A daily call cap figure was cut off in the extracted snippet.
- Rijksmuseum IIIF image URL patterns and data-dump format were not checked.
- Cooper Hewitt GraphQL authentication and rate limits were not documented on the fetched page.

## Coverage of the four design domains and image style

### Takeaway
Wristwatches are very poorly covered: museum timepieces are mostly 16th–19th-century pocket watches and clocks, and almost no modern wristwatches are open-access. Historical costume and textiles are well covered (Met, Smithsonian/Cooper Hewitt, Rijksmuseum, AIC), but 20th-century couture at the Met is largely not public domain. Furniture and decorative arts are strong everywhere. Posters and graphic design are moderate, mainly historical prints, wallcoverings and posters. No source provided open-access "digital interface" (UI) imagery.

### Cited Findings (all from live queries on 2026-10-26; keyword counts are estimates)
**Met** (`v1.1/search?hasImages=true`): totals are upper bounds, and the public-domain share comes from a sample of 20 objects per query
- "watch": 2,272 results; 18/20 sampled were public domain with image URLs, all with objectName "Watch". **Estimate: about 2,000 public-domain watch images, nearly all pocket and pre-1900 watches.**
- "clock": 1,385 results; 17/20 public domain.
- "chair": 7,285 results; 14/20 public domain.
- "evening dress": 3,194 results; **0/20 public domain** and 0 with image URLs. Costume Institute evening wear is mostly restricted.
- "dress" 32,608, "costume" 47,708, "textile" 44,087 and "furniture" 11,692 are raw keyword totals with no public-domain sampling.
- "poster": 9,246, but the results were noisy (dresses, nightgowns, photographs) and 2/20 were public domain.
- Costume Institute department holds 31,898 object IDs in total.
- Hit counts did not match the keyword reliably ("poster" returned dresses), and search did not filter on public domain.

**Smithsonian Open Access, all units** (`q=<term> AND online_media_type:Images`; not CC0-filtered; only some queries completed before the DEMO_KEY cap)
- wristwatch 190; watch 4,216; clock 1,610; dress 22,408; costume 23,712; textile 28,745.
- Cooper Hewitt only (`unit_code:CHNDM`): watch 193; clock 267; dress 766; costume 1,955; wristwatch 0.

**Cooper Hewitt via S3 bulk sample** (8 of 256 CHNDM shards, 1,800 records)
- 1,678 of 1,800 records had media, and every media item was CC0.
- Top object types with CC0 media: Print 312, Wallcoverings 128, figures 105, embroidery & stitching 85, woven textiles 83, architecture 69, bound print 68, drawing 67, printed/dyed/painted textiles 62, lace 57, costume & accessories 56, furniture 34, interiors 21, textile designs 18.
- Scaling by 32 (rough estimate, assuming even shards): about 57,000 CHNDM records; about 12,000 costume/textile CC0 objects; about 5,400 furniture/wallcovering/interior CC0 objects; about 18,000 graphic/print/drawing CC0 objects; watches/clocks near zero (1 in the sample).

**AIC** (multi_match on title, classification and term fields; public domain plus image_id, compared with all objects that have images)
- watch 84 / 132; pocket watch 139 / 201 (the OR match inflates this); clock 56 / 92; dress 709 / 1,121; costume 2,398 / 3,198; textile 7,028 / 11,634; furniture 460 / 978; chair 247 / 634; poster **47** / 916; "graphic design" 647 / 4,273.
- Most posters at AIC are not public domain.

**Rijksmuseum** (`type=` with `imageAvailable=true`)
- horloge (watch/clock) 204; zakhorloge (pocket watch) 29; polshorloge (wristwatch) 0; klok 117; japon (gown) 221; kostuum 6; stoel (chair) 592; kast (cabinet) 293; **affiche (poster) 4,998**.
- `imageAvailable` does not mean CC0. Licence status must be checked per object.

**V&A** (`images_exist=1`; licence not open)
- watch 3,275; clock 2,291; dress 76,777; costume 45,894; textile 91,543; furniture 17,029; chair 11,683; poster 20,666; graphic design 2,227; "user interface" 8.
- This is the richest source for design topics, but its terms are restrictive.

**Europeana** (`reusability=open`, `media=true`, `TYPE:IMAGE`)
- wristwatch 199; watch 2,828; clock 12,453; dress 45,018; costume 53,663; textile 108,829; furniture 33,153; chair 8,997; poster 15,199; graphic design 650.
- These figures include many photographs and documents from many providers, not only studio object shots.

**Image style**: Smithsonian media includes accessibility alt text and descriptions, e.g. "Design for a candlestick decorated with scalloping, acanthus leaf...". — [SI S3 sample](https://smithsonian-open-access.s3-us-west-2.amazonaws.com/metadata/edan/chndm/index.txt)

### Inferences
- **Wristwatches**: open-access museum images will not provide a contemporary wristwatch corpus. Smithsonian's 190 "wristwatch" hits and Europeana's 199 open hits are the only meaningful pools. Expect pocket watches, enamel cases, movements and clocks shot as studio object photos on neutral backgrounds.
- **Fashion**: plenty of historical garments, textiles, lace, embroidery and textile designs (Cooper Hewitt and AIC textiles are strong). 20th-century couture at the Met is mostly not public domain, based on the 0/20 sample.
- **Interiors/furniture**: strong at the Met (chairs about 70% public domain in the sample), Rijksmuseum and Cooper Hewitt (wallcoverings, interiors drawings). These are mostly isolated object photos, with few room-scale interior photographs apart from Cooper Hewitt "interiors" drawings.
- **UI/graphic design**: open-access coverage is historical posters (Rijksmuseum about 5,000 with images, licences to verify), prints, ornament and wallpaper. Modern graphic design and digital interfaces are essentially absent or in copyright (V&A has 8 "user interface" hits under restrictive terms; AIC has only 47 public-domain posters). Another source is needed for UI references.
- Image style overall: museum studio photography on grey or white backgrounds, historical objects (mostly pre-1926 because of public-domain rules), mixed with scanned prints and drawings. This is very different from contemporary product or lifestyle imagery.

### Gaps
- No exact per-domain open-access counts exist from any source. All figures above are keyword or sample-based estimates. A precise Met count would need the MetObjects.csv filtered on "Is Public Domain" plus a classification field, which was not downloaded.
- Smithsonian CC0-filtered counts for furniture, chair, poster and graphic design were not obtained because the DEMO_KEY limit was hit. A real api.data.gov key is needed.
- The Rijksmuseum CC0 share within the `imageAvailable` results was not sampled.

## Practical gotchas

### Takeaway
The main practical risks are dead endpoints in older tutorials, bot protection (Met Imperva, AIC and si.edu Cloudflare) that can block rapid or GET-based clients, tiny DEMO_KEY quotas, search filters that are ignored, and many hits without open images.

### Cited Findings
- **Met**: a rapid loop over `/v1/objects/{id}` got empty or non-JSON responses (Imperva CDN headers, `X-CDN: Imperva`), even though the documented limit is 80 requests per second. Adding a 0.4-second delay fixed it. — live API; [Met API docs](https://metmuseum.github.io/)
- **Met**: `/v1/search` is retired. v1.1 ignores `isPublicDomain`, and `hasImages=true` includes objects with no open image (empty `primaryImage`). — live API
- **Smithsonian**: DEMO_KEY was exhausted after about 22 calls, with a 9-hour retry-after. — live API
- **Smithsonian**: the CC0 media rule means records may have metadata but no image file. — [si.edu devtools via search](https://www.si.edu/openaccess/devtools)
- **AIC**: GET requests hit a Cloudflare challenge from the research environment, while POST worked. In the Elasticsearch body, a `query` overrides `q`; the first attempt returned the same total (59,061) for every term until `multi_match` was used. — live API
- **Rijksmuseum**: search returns IDs only, so each record and image needs extra calls (N+1 pattern). Type terms are vocabulary-specific: `jurk` and `meubel` returned 0, `japon` returned 221. — live API
- **Cooper Hewitt**: legacy REST URLs redirect or return 404. Use Smithsonian Open Access. — live HTTP checks
- **V&A**: the four-week cache limit and mandatory hotlinking. — [V&A terms §9.3](https://www.vam.ac.uk/info/va-websites-terms-conditions/)

### Inferences
- Recommended pipeline:
  1. Seed from bulk metadata: the Met CSV, Smithsonian S3 CHNDM and other units, and AIC/Rijksmuseum dumps.
  2. Filter on each source's licence flag.
  3. Fetch images only from the official image URL fields, with throttling and a descriptive User-Agent.
  4. Store per-image provenance (museum, object ID, accession number, licence, source URL) to produce the credits page.

### Gaps
- Overall image-missing rates per source were not measured, apart from the Met samples and the Cooper Hewitt sample (122 of 1,800 CHNDM records, about 7%, had no media).
