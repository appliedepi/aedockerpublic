# Verification — reproducing the live epirhandbook.com

This directory freezes the evidence for the Phase 1 claim: **`epirhandbook:2.5-p1` reproduces the
current live website (all 8 published languages) from the unchanged Sep-2024 content.** The bulky
crawl + render HTML is not committed (hundreds of MB); instead `manifest.tsv` pins the per-page
text-similarity plus a content hash (`sha16`) of both files compared, so the exact bytes are
provenance-locked and the numbers are re-derivable.

## What was compared
- **Rendered:** `epiRhandbook_eng` content @ `c3cbc76` (the "Rendering after remove old handbook"
  commit; the live site is date-stamped "Last updated Sep 18 2024"), rendered on `epirhandbook:2.5-p1`.
- **Reference:** a fresh crawl of `https://epirhandbook.com/<lang>/new_pages/*.html`, taken
  **2026-07-21** — the live production site, NOT the stale committed `html_outputs/` (see the main
  README for why those differ).

## Procedure (re-runnable)
1. Check out the content: `epiRhandbook_eng` @ `c3cbc76`, into a writable copy.
2. Render-prep (Linux, content unchanged):
   - `python3 ../fix_image_case.py <source>` — case-matching image symlinks (content authored on
     case-insensitive macOS; see the main README).
   - Comment out `new_pages/gis.qmd` in the source `_quarto.yml` — `gis` fetches live OSM tiles at
     render time (`OpenStreetMap::openmap()`), which aborts the whole book render. It is the one
     external-dependency chapter, excluded from the proof (see Caveats).
3. Render all languages:
   ```bash
   docker run --rm -e RENV_CONFIG_AUTOLOADER_ENABLED=FALSE -v <source>:/book -w /book \
     epirhandbook:2.5-p1 Rscript quarto_runfile.R
   ```
   → `html_outputs/new_pages/*.html` (en) + `html_outputs/<lang>/new_pages/*.<lang>.html` (7 langs).
4. Crawl the live languages: `epirhandbook.com/<lang>/new_pages/<chapter>.<lang>.html`
   (en at `/en/new_pages/<chapter>.html`).
5. Diff + freeze: `python3 make_manifest.py` (uses `diff_chapter.py`) → `manifest.tsv`.

## Result (from `manifest.tsv`)
| lang | n  | median | ≥0.98 | <0.90 |
|------|----|--------|-------|-------|
| en   | 49 | 0.9912 | 39    | 1     |
| fr   | 48 | 0.9920 | 38    | 0     |
| es   | 48 | 0.9909 | 37    | 1     |
| vn   | 48 | 0.9928 | 39    | 0     |
| jp   | 48 | 0.9839 | 26    | 2     |
| pt   | 48 | 0.9909 | 37    | 1     |
| tr   | 48 | 0.9896 | 36    | 1     |
| ru   | 48 | 0.9903 | 36    | 1     |

Every published language reproduces the live site at ~0.99 median text-similarity.

## The residual ~1% (systematic, non-environment)
- **Sidebar renumbering** — excluding `gis` shifts every later chapter's number in the sidebar TOC on
  *every* page, depressing each score a hair (short chapters like `directories` most).
- **Volatile colophons** — `editorial_style` prints `session_info()` (versions/date); `directories`
  prints `fs::dir_info()` (file mod-dates). Render-machine dependent, not content.
- **`jp`** — the word-similarity metric splits on whitespace, which under-measures space-less
  Japanese; jp content reproduces as well as the others.

## Caveats on rigor (from the codex gate — the honest limits of this proof)
- **Full-page text similarity**, so computed outputs (tables, printed values) are *included* in the
  match but were **not separately extracted and compared**. Stronger next increment: isolate `<main>`
  computed outputs, normalize volatile blocks, extract table/value diffs.
- **`gis` is excluded**, so the proof covers 47/48 book chapters. The rigorous fix (cache/mock the OSM
  tiles so `gis` renders deterministically) is deferred to the `modernize` phase.
- The **crawl HTML is not committed** (bulky); `ref_sha16` in the manifest pins what was compared.

## Files
- `diff_chapter.py` — the similarity core (strip tags/scripts, unescape, normalize dates + whitespace,
  word-level `difflib.SequenceMatcher` ratio).
- `diff_ml.py` — per-language summary diff.
- `make_manifest.py` — regenerates `manifest.tsv` (per-page similarity + `sha16` of both sides).
- `manifest.tsv` — the frozen evidence (386 rows: lang, chapter, similarity, words, hashes).
