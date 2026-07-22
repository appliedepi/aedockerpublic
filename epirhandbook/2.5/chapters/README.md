# Phase 3 — per-chapter rendering of epiRhandbook

Renders each English chapter individually, on the same full 473-package Phase 2 image
(`epirhandbook:2.5-p2ubuntu`), and checks two things: (1) how closely each chapter's standalone HTML
compares to that chapter's page from the Phase 2 full-book render — page **text** similarity
(`compare_chapters.py`), generated-asset (figure) hashing and pixel-diffing (`compare_assets.py`),
and inline-widget-JSON-payload comparison (`compare_widgets.py`), each measured and reported
separately, because none of the three alone sees what the other two see — and (2) which packages
each chapter's render actually loads. Only the render **granularity** changes here — same content,
same package set, same image. This is the input to the Phase 5 per-chapter image split.

## Method

### Setup
- Working copy: `cp -a ~/ae/render_sep18 ~/ae/render_p3` on compute, then `rm -rf
  ~/ae/render_p3/html_outputs` — every file compared below is provably fresh, not a leftover
  book-render page, because `html_outputs/` did not exist at all before this run.
- `~/ae/render_p3/_quarto.yml` was checked against `~/ae/render_sep18/_quarto.yml` right after the
  copy (`diff` → identical). It already has `gis` commented out of the book's `chapters:` list
  (`#- new_pages/gis.qmd EXCLUDED-osm-external-dep #done`), inherited unchanged from the Phase 2
  render-prep. Also already commented out there (not previously called out): `plot_continuous`,
  `plot_discrete`, `relational_databases`, `rstudio_advanced` — see Chapter reconciliation below.
  `fix_image_case.py` was likewise inherited unchanged via the copy; no new image-case failures
  appeared in this run, so it still holds.
- Render command (per chapter):
  ```bash
  docker run --rm -e RENV_CONFIG_AUTOLOADER_ENABLED=FALSE \
    -v ~/ae/render_p3:/book -v ~/ae/p3:/p3 -w /book \
    epirhandbook:2.5-p2ubuntu bash render_chapters.sh
  ```
  `render_chapters.sh` loops `quarto render new_pages/<chapter>.qmd` (or `quarto render index.qmd`)
  over every chapter inside one container invocation, 600s timeout per chapter (guards `gis`'s live
  network fetch; never bound in practice — see Results). `/p3` is a second bind mount used only for
  evidence output (render log, per-chapter logs, package footprints), kept entirely outside `/book`
  so it cannot be seen or copied by quarto's own project/book machinery.

### Package footprint capture
`capture_footprint.R` registers a knitr **document** hook — fires once, after all of a chapter's
code chunks have already executed, and must return its input unchanged (it does: the hook's only
effect is the file write). It writes `sort(loadedNamespaces())` to `/p3/footprints/<chapter>.txt`.
Wired in via a one-line `.Rprofile` (`source("capture_footprint.R")`) placed in the `render_p3`
working copy — never inside a `.qmd` — because `Rscript`, which quarto/knitr shell out to for each
chapter, reads `.Rprofile` from the current working directory by default, and each `quarto render`
call is a fresh R process (no persistent kernel for the knitr engine), so no cross-chapter leakage.
This is why footprints.tsv reflects what the render actually loaded, not a `library()`/`p_load()`
source scan.

A chapter with **zero executable R chunks** never invokes knitr at all (quarto uses the plain
`markdown` engine instead), so the hook never fires and there is no footprint row for it. That's
not a capture bug — see Package footprints below, it's a real and useful signal.

### Comparison
`compare_chapters.py` uses `diff_chapter.py`'s metric (`epirhandbook/2.5/verify/diff_chapter.py`)
completely unchanged, imported directly rather than copied. For each chapter with a book reference
page, it computes the same word-level `difflib` ratio over stripped/normalized text that
`verify/manifest.tsv` used. Chapters with no book reference page get a blank `similarity_vs_book`
and a note explaining why (see Chapter reconciliation).

## Results

### Render outcomes
**68 chapters attempted (67 English `new_pages/*.qmd` + `index.qmd`): 66 OK, 2 FAIL.**

| chapter | seconds | error |
|---|---|---|
| `gis` | 14 | ``Error in `osmtile()` `` |
| `plot_continuous` | 2 | `could not find function "drop_na"` |

Both are the two pre-existing failures the brief names, reproduced exactly: `gis` fetches live
OpenStreetMap tiles (fails fast here — 14s, not a hang — but the 600s timeout would have caught a
genuine hang); `plot_continuous` never calls `library(tidyr)`. **Neither is a Phase 3 regression.**
Every one of the 49 book chapters + `index` — i.e. every chapter that is actually part of the
published book — rendered successfully. All render outcomes are in `results.tsv`.

### Chapter reconciliation: 67 English `.qmd`, 49 in the book, 18 not
The brief estimated ~53 English chapters; the real count is **67** (`ls new_pages/*.qmd | grep -vE
'\.[a-z][a-z]\.qmd$'`), of which only **49** are wired into `_quarto.yml`'s book `chapters:` list
(the ones with a page in `ref_p2_book/`). The other 18 fall into two groups:

**5 have real content but are explicitly commented out of `_quarto.yml`:**
| chapter | render result | why excluded |
|---|---|---|
| `gis` | FAIL (`osmtile()`) | live OpenStreetMap fetch (brief-documented) |
| `plot_continuous` | FAIL (`drop_na`) | missing `library(tidyr)` (brief-documented) |
| `plot_discrete` | **OK** (5s) | substantial real content (283 lines, real ggplot2 code) — renders cleanly standalone; no technical reason for the exclusion is evident in the source |
| `relational_databases` | OK (4s) | "THIS PAGE IS UNDER CONSTRUCTION" stub |
| `rstudio_advanced` | OK (2s) | "THIS PAGE IS UNDER CONSTRUCTION" stub |

**13 are never mentioned in `_quarto.yml` at all** (not even commented out) — orphaned `.qmd` files
sitting in `new_pages/` that no book profile references:
- 10 are one-line `# (PART) ... {.unnumbered}` PART-divider stubs (`cat_about_book`, `cat_advanced`,
  `cat_analysis`, `cat_basics`, `cat_data_management`, `cat_data_viz`, `cat_introduction`,
  `cat_misc`, `cat_preview`, `cat_reports_dashboards`) — a different navigation structure's
  scaffolding, not chapter content.
- `apply_functions` (79 lines) and `modeling` (55 lines) are template skeletons — placeholder
  instructional text ("Keep the title of this section as...", "UNDER CONSTRUCTION"), zero R code.
- `descriptive_statistics` (932 lines, 52 R chunks) is substantial real legacy content, apparently
  superseded by `tables_descriptive.qmd`.

All 18 were still attempted (per the brief's instruction to render every English `.qmd` in
`new_pages/`, not just the book's 49) — 16 rendered OK, 2 failed as already covered.

### A render-location surprise: book vs. standalone output path
The 16 non-book chapters that rendered OK did **not** land in `html_outputs/`. Quarto only routes a
file through the book's `output-dir` when that file is in `_quarto.yml`'s `chapters:` list; anything
else renders as a plain **standalone** document (`standalone: true` in its own resolved format) and
the output lands next to the source — `new_pages/<chapter>.html`, sibling to the `.qmd`, e.g.
`~/ae/render_p3/new_pages/descriptive_statistics.html` (287 KB, real content) — confirmed by each
chapter's own log (`Output created: descriptive_statistics.html`, no path prefix, vs. book chapters'
`Output created: html_outputs/new_pages/basics.html`). This is orthogonal to whether a chapter has
live R code: `plot_discrete`/`relational_databases`/`descriptive_statistics` (real code, real
`loadedNamespaces()` footprints) land here exactly the same as the empty PART-stubs. It has no
effect on the 49-chapter book comparison — none of these 18 chapters has a book reference page to
compare against regardless of where their HTML lands — but it means html_outputs/new_pages/*.html
contains **exactly the 49 book chapters, no more** (confirmed: file-name set identical to
`ref_p2_book/new_pages/`).

One more render-location subtlety confirmed by direct test: rendering any single non-`index`
chapter *also* regenerates `html_outputs/index.html` as a 227-byte placeholder/redirect stub (book
navigation scaffolding quarto creates on demand) — this is **not** a real render of the index
chapter. Rendering `index.qmd` explicitly replaces it with the real 73 KB page, and that real page
survives every subsequent chapter's render undisturbed (tested: rendered `index`, then `cleaning`,
re-checked `index.html` — still 73,092 bytes, same content). `index` is included in every count
above as chapter 68/68.

### Similarity vs. book (50 chapters compared: 49 book chapters + index)
**Median 0.9991, min 0.9740, max 0.9997. 26/50 ≥ 0.999, all 50 ≥ 0.974** (full numbers:
`results.tsv`). Every chapter below 0.999 was individually inspected — word-level diff opcodes
against the actual reference HTML, not just the score — and falls into one of five fully-explained,
non-regression causes. **This score is a TEXT comparison only** — `diff_chapter.py` strips all
markup (`<script>`/`<style>`/tags) before scoring, so it cannot see a figure, an embedded htmlwidget,
or any other rendered asset; a page could in principle score 1.0000 here with a completely different
image sitting in it. **No computed value, statistic, or table entry differs from the book render
anywhere in this comparison**, except the two already-known-volatile pages this run newly reconfirms
(`transmission_chains`, and — newly observed here because the two renders happened a day apart —
`dates`/`index`/`directories`). What figures/widgets actually do is checked separately below
("Generated assets vs. book"), by hashing, not by this text score.

#### (a) Universal: multi-language navbar — present in ALL 50 comparisons
Every single chapter, including the ones scoring ≥0.999, shows this as its first diff hunk:
```
[insert] b: 'Français Español Tiếng Việt 日本 Português Türkçe Русский'
```
The book reference is part of the babelquarto multi-language build and carries a language-switcher
in its navbar; the individual English-only render has no babelquarto context, so it's absent. Fixed
~7-word gap on every page — book chrome, zero content effect. This alone is why even a
content-identical chapter cannot reach 1.0000.

#### (a) gt/gtsummary table `id`-attribute escaping — 4 chapters
`stat_tests` (0.9740, the lowest score), `regression` (0.9863), `tables_descriptive` (0.9945),
`survey_analysis` (0.9970) — every one of their sub-0.999 diff hunks, without exception, is this
same pattern. Traced to the raw HTML: a `gt`-generated table column header built from bold markdown
(`**Characteristic**`) gets used as the table's `id` attribute value. In my standalone render:
```html
<th id="<strong>Characteristic</strong>" class="gt_col_heading ...">
```
In the book reference:
```html
<th id="&lt;strong&gt;Characteristic&lt;/strong&gt;" class="gt_col_heading ...">
```
The book version HTML-escapes the `<`/`>` inside the attribute value; the standalone version
doesn't. `diff_chapter.py`'s tag-stripper (`<[^>]+>` → space) can't fully remove the unescaped
version — it matches only up to the embedded `>`, leaking `" class="gt_col_heading
gt_columns_bottom_border gt_left" data-quarto-table-cell-role="th" scope="col">` as visible "text",
which is what the diff shows as a spurious deletion. Same package versions (Phase 2 is pinned)
render both sides; only the render **context** (standalone `.qmd` vs. book-project chapter) changes
how quarto's HTML-escaping pass treats this one invisible, CSS/JS-internal attribute. Confirmed by
direct inspection: the actual visible table content — `Characteristic`, `Death, N = 2,582`,
`Recover, N = 1,983`, every OR/CI/p-value — is byte-identical in both. **Not a computed-output
difference** — nothing a reader of the page would ever see differs.

#### (a) Render-timestamp / render-environment fields — `index`, `dates`, `directories`
- **`index`** (0.9955): `[replace] a='22,' b='21,'` — the `date: today` YAML field; my render ran
  Jul 22, the book reference Jul 21. Front-matter date stamp only.
- **`dates`** (0.9977): several `Sys.time()`/`Sys.Date()` replacements (`16:22:48`→`17:08:43`,
  `Wed`/`Wednesday`→`Tue`/`Tuesday`, `22`→`21`). This chapter's own teaching content **is** "print
  today's date" — it is expected to differ whenever the two renders happen on different days/times,
  by design, not by defect. Not previously flagged as volatile because earlier verification passes
  rendered same-day; this run's book reference and per-chapter render are ~1 day apart.
  `directories` prints `fs::dir_info()` mod-times.
- **`directories`** (0.9952): `/book/data` → `/tmp/RtmpKTcC1E/file173ba71a3/data` (the working
  directory each render happened in) and a differing file-modification timestamp. Already flagged
  as a known-volatile page in the Phase 1/2 README for exactly this reason.

`editorial_style` (0.9978, prints `session_info()`, also previously flagged as volatile) showed
**zero** extra diffs beyond the universal navbar in this comparison — its package/R/OS-version
output is actually identical between the two renders, since both share the same pinned image. A
reassuring confirmation, not a new finding.

#### (b) Genuine computed-output difference — but a pre-existing known-volatile chapter
- **`transmission_chains`** (0.9897): real value changes throughout — case-ID hashes, `Nosocomial`
  vs `Community` classification counts, row totals (`1,916`→`1,927`). This chapter's contact-network
  simulation has no fixed random seed. Already documented in the Phase 1/2 README
  ("`transmission_chains` uses a stochastic network layout"); this run reconfirms the same
  pre-existing volatility, not something the per-chapter render approach introduced.

No other chapter showed any hunk beyond the universal navbar line — i.e. every chapter not named
above is **word-for-word identical** to its book page, modulo that one fixed navbar difference.

### Generated assets (figures) vs. book
The text score above cannot see a figure or a widget — it strips all markup before scoring. To help
cover that, `compare_assets.py` separately sha256-hashes (and, for a mismatching image, genuinely
pixel-diffs) every file in each of the 49 book chapters' + index's generated asset directory
(`<chapter>_files/`, e.g. `figure-html/*.png`) on both sides, file-for-file. Results: `assets.tsv`
(one row per file). **This directory, in this handbook, only ever contains figures** — every
htmlwidget (DT/plotly/...) this handbook produces embeds its data **inline in the chapter's own
HTML**, never as a separate file under `_files/` (confirmed: zero non-image files exist under any
`_files/` directory in this dataset). So `compare_assets.py` covers figures only; inline widget
payloads are a **separate** check, `compare_widgets.py` (`widgets.tsv`), described below — an earlier
version of this section implied the `_files/` walk already covered widgets too, which was never
actually true for this content.

**25 of the 50 chapters produce no `_files/` directory on either side at all** (no figures —
text/table-only chapters, and `index`) — reported as 0/0, a valid outcome, not a gap. Of the 25 that
do produce one, every one has the **same file count on both sides** (258 files total, in every case
the same filenames) — quarto's figure-naming is deterministic given identical chunk labels/order.
**249/258 (96.5%) hash byte-identical. 9 files across 5 chapters differ** — every one individually
pixel-diffed (`PIL.ImageChops.difference`, on the two images converted to plain RGB — see
`compare_assets.py` for why RGBA must be avoided here, it silently produces false 0.0000% diffs on
this image set), not just byte-diffed, to tell a cosmetic difference from a real one. These
percentages are `compare_assets.py`'s own committed, reproducible output (`assets.tsv`), not a
figure computed by hand outside the script:

| chapter | files differing | pixel-diff (from `assets.tsv`) | cause |
|---|---|---|---|
| `age_pyramid` | 1 | 0.0130% (tiny, localized to the caption) | `Sys.Date()` interpolated into a plot **caption string** — same render-date root cause already documented for `dates`/`index`/`directories`, here reaching into a figure's pixels instead of text |
| `epidemic_models` | 2 | 0.8311%, 16.4060% | **unseeded stochastic simulation**, not a render-date artifact. `projections::project()` and the `rgamma()` draw feeding it run with no `set.seed()`, so these figures differ **run to run**, on the same date, on the same image — see "Task 1: settling run-to-run vs. instrumentation" below, which proves this directly (a clean A/A re-render, and reproducibility restored by adding `set.seed()`) rather than inferring it |
| `combination_analysis` | 1 | 2.7228% | `sample(c("yes","no"), ..., prob=...)` generates the chapter's demo symptom columns fresh every render; no `set.seed()` anywhere in the source — a real, **previously-undocumented** per-render volatility in the chapter's own content, unrelated to Phase 3's per-chapter render approach. (Source-identified only; not independently re-rendered/re-verified the way `epidemic_models` and `ggplot_basics` were.) |
| `ggplot_basics` | 2 | 13.7939%, 10.7425% | the jitter/sina/violin demo (`geom_jitter()`, `geom_sina()`); no `set.seed()` in the source — confirmed by the same A/A + `set.seed()` test as `epidemic_models` (below) |
| `ggplot_tips` | 3 | 3.3438%, 0.6625%, 0.0007% | two use `ggrepel::geom_label_repel()`'s unseeded stochastic label-repulsion layout (no `set.seed()` in the source, previously-undocumented volatility); the third (0.0007% = 9 pixels of 1.29M) is antialiasing-scale noise, not a content difference. (Source-identified only, like `combination_analysis`.) |

`transmission_chains` — already documented as volatile in its page **text** (case-ID hashes,
`Nosocomial`/`Community` counts) — is notable for the opposite reason: its two hashed figures
(pairwise/cluster-size plots) matched **exactly** (identical sha256) in this comparison. Its
volatility shows up in this chapter's text (and, see `widgets.tsv` below, its widgets), not in these
two particular images.

None of the 9 asset mismatches are a Phase 3 regression, and none is an unexplained mismatch:
`compare_assets.py` exits non-zero on any mismatch outside its explicit allowlist, and all 9 are on
it. **An allowlist entry excuses a known, bounded difference — not any difference at that path.**
Four conditions are checked and none of them is itself allowlistable:

1. The file must exist on **both** sides. `render-only`/`ref-only` is always fatal — a figure that
   vanished is a broken comparison, not tolerable variation.
2. The image must be **readable** by PIL. An unreadable or corrupt file is fatal.
3. Dimensions must **match**.
4. The pixel difference must be within that path's documented **ceiling** (`MAX_PIXEL_DIFF_PCT`,
   roughly 2.5x the observed value with a 5% floor — sized generously, because these figures are
   genuinely stochastic and an honest re-render may vary more than the run recorded here; the
   ceilings exist to catch corruption and wholesale replacement, not to police the variance of a
   random draw).

Both earlier versions of this logic were holes, and both were found by adversarial review: the first
applied the allowlist to any non-match status, so **deleting** an allowlisted figure exited 0; the
second bounded nothing, so **replacing** one with a corrupt file, a different-sized image, or an
entirely different picture exited 0. Each fix was verified by inducing exactly that case in an
isolated sandbox — deleted file, corrupt file, 100x100 image against a 1344x960 reference, and a
same-dimension image differing by 100.0000% against a 9.0% ceiling. All four exit 1 with an explicit
`FATAL` reason; the clean run is unchanged at 258 files / 249 matched / 9 mismatched, exit 0.
A `MAX_PIXEL_DIFF_PCT` and `ALLOWLIST` key-set assertion keeps the two tables in lockstep, so an
allowlist entry can never be added without a bound.
One (`age_pyramid`) is the render-date artifact already known from the text comparison, reaching
a figure for the first time. The other 8 are **genuine per-render volatility already present in the
chapter's own source** (unseeded `sample()`, `geom_jitter()`/`geom_sina()`, `ggrepel`, and
`rgamma()`/`projections::project()`), not something the per-chapter render granularity introduced —
the same `.qmd` renders the same way inside the full book. Two of the five chapters
(`epidemic_models`, `ggplot_basics`) are confirmed by direct re-render experiment, not just source
inspection — see "Task 1" below. Full per-file detail, including byte sizes on both sides for every
mismatch: `assets.tsv`.

### Inline widget payloads vs. book
Neither check above sees an htmlwidget's actual data: `compare_chapters.py` strips `<script>`/
`<style>` before scoring text, and `compare_assets.py` only walks `_files/` — which, as just
established, never holds this handbook's widget data anyway (it's inlined in the HTML). A DT/plotly/
leaflet payload that genuinely changed would therefore have been invisible to **every** check in this
phase, and is exactly what `compare_widgets.py` (`widgets.tsv`) covers: it extracts every `<script
type="application/json" data-for="htmlwidget-...">` payload from both sides, normalizes the random
per-render identifiers, and compares what's left.

Two identifiers are normalized, both random and content-free — nothing else (no date normalization,
no rounding): (1) the htmlwidget DOM id itself (`htmlwidget-XXXXXXXXXXXXXXXXXXXX`), regenerated every
render to wire a `<div>` to its `<script>`; (2) plotly's own **separate** internal `"cur_data"` key
(and its recurrence as a `visdat`/`attrs` dict key in the same payload) — a second, independent
random id that only surfaced by running this check against the real data: without normalizing it,
`interactive_plots` and `diagrams` (both plotly) reported 5 "genuine" mismatches that were actually
just this id changing. Verified, not assumed: normalizing only that one extracted token made all 5
payloads byte-identical to the book reference, confirmed by direct before/after diffing.

Across 50 chapters, 175 widget payloads were compared (position-matched — the Nth widget on each
side — since ids can't be matched by identity): **162 match, 13 do not**, all 13 fully explained and
none a regression:
- **`epidemic_models` (1 payload)** — the projection-results `DT` table; the actual simulated case
  counts differ, independent corroborating evidence (via a completely different code path than the
  figures) for the same unseeded `rgamma()`/`project()` finding as above.
- **`transmission_chains` (10 payloads)** — already-documented stochastic contact-network simulation;
  its widgets carry the same volatility already known from this chapter's page text. All but one of
  this chapter's 11 payloads differ (`widget_index` 0 and 2–10; only index 1 matches).
- **`directories` (2 payloads)** — already-documented volatility: the widget content includes the
  render's own working-directory path (`/book` vs. quarto's `/tmp/Rtmp.../file...` for the book
  build) and file modification timestamps, both expected to differ run to run by design.

No chapter has a different widget count between the two sides. Full detail: `widgets.tsv`.

### Task 1: settling run-to-run vs. instrumentation (round-2 remediation)

An earlier version of this section compared 52 `ggplot_basics` + `epidemic_models` figures between
`render_p3` (instrumented with the `.Rprofile`/`capture_footprint.R` hook) and `render_p3_noinstr`
(not instrumented), found the same 4 figures differing every time, and concluded the cause was
unseeded RNG. **That comparison changed two variables at once** — run identity (two separate render
invocations) *and* instrumentation (present vs. absent) — so on its own it cannot distinguish "this
figure differs run to run, regardless of instrumentation" from "the instrumentation itself perturbs
the render." The "Instrumentation neutrality" section below only ever compared page **text** (via a
parser that structurally skips `<script>`/`<style>` content), never figures, so it could not settle
this either. A second adversarial review correctly flagged this as unsettled. Below is the clean
test that actually isolates the two variables.

**The A/A test: two fresh trees, identical instrumentation, only run identity differing.**
`~/ae/aa_run1` and `~/ae/aa_run2` were both built the same way as `render_p3` (`cp -a
~/ae/render_sep18`, `rm -rf html_outputs` so no pre-existing output could leak in) and both given the
byte-identical `.Rprofile` + `capture_footprint.R` (diffed against each other and against `render_p3`'s
copy — identical). Both rendered `epidemic_models` and `ggplot_basics` independently (separate
container invocations); the footprint hook fired and wrote its output in both (confirmed:
`epidemic_models.txt`/`ggplot_basics.txt` present in both runs' evidence directories), proving the
instrumentation was genuinely active in both, not merely present-but-inert. All 52 figures (11
`epidemic_models` + 41 `ggplot_basics`) were then sha256-hashed and compared pairwise:

| Figure | run1 sha256 (16 hex) | run2 sha256 (16 hex) | match |
|---|---|---|---|
| `epidemic_models_plot_projection-1.png` | `d18d0dbd0a8ce795` | `6882288b4fab1389` | **DIFFER** |
| `epidemic_models_projection_setup-1.png` | `cee8c21148ca20f9` | `0512e3f1f40bd314` | **DIFFER** |
| `ggplot_basics/unnamed-chunk-40-1.png` | `7fbc2ea0d2080c08` | `f387dc0f26574801` | **DIFFER** |
| `ggplot_basics/unnamed-chunk-41-1.png` | `d290561282828d6d` | `a923e0845f9c39ea` | **DIFFER** |
| (all other 48 figures) | — | — | MATCH |

**Interpretation.** With instrumentation held constant across both trees, the exact same 4 figures —
no more, no fewer — still differ, and no OTHER figure newly differs. This settles both questions at
once: (1) these 4 figures are genuinely run-to-run non-deterministic — instrumentation cannot be the
cause, since it was identical in both trees; (2) instrumentation is fully exonerated as a factor in
the *original* (confounded) finding too, because holding it constant reproduces the identical set of
differing figures — if instrumentation had been perturbing anything, this controlled comparison would
have shown a different pattern (fewer, more, or different figures differing), and it did not.

**Bonus evidence for the `.quarto/_freeze` claim below:** before rendering, both trees' inherited
`.quarto/_freeze/new_pages/{epidemic_models,ggplot_basics}/execute-results/html.json` (from
`render_sep18`, dated 2026-07-21) were recorded (sha256 `28505e57b3f4b895` / `7a21134336695f05`).
After rendering `aa_run1`, both files had a **new** sha256 (`730be72910d4370a` / `672f9242aedead7f`)
and a fresh mtime — direct proof these two chapters genuinely re-executed rather than being served
a cached result, extending the write-only confirmation below from one chapter (`age_pyramid`) to
three.

**Direct causal proof: seeding fixes it.** A/A hashing shows *that* these figures are run-to-run
non-deterministic; it doesn't by itself prove *why*. So the mechanism was confirmed directly: a
throwaway tree was copied from `render_sep18` (the pristine source itself was never edited), and
`set.seed(1)` was inserted as the first line of the `epidemic_models_projection_setup` chunk (which draws `plausible_r
<- rgamma(1000, ...)`, consumed by `project()` in the following chunk with no intervening code) and,
separately, as the first line of `ggplot_basics`'s chunk 40 (the unnamed `geom_jitter()`/`geom_sina()`
chunk — the only chunks in ggplot_basics.qmd are unnamed, so this IS the chunk knitr auto-labels
`unnamed-chunk-40`; chunk 41's `geom_sina()` draws from the same continuing RNG stream, with no
intervening chunk to reseed it). Each modified chapter was then rendered **twice**:

| Chapter | Figure | Render 1 sha256 (16 hex) | Render 2 sha256 (16 hex) | match |
|---|---|---|---|---|
| `epidemic_models` (seeded) | `plot_projection-1.png` | `d2da3083d80a4532` | `d2da3083d80a4532` | **MATCH** |
| `epidemic_models` (seeded) | `projection_setup-1.png` | `59734ec6fcb66765` | `59734ec6fcb66765` | **MATCH** |
| `ggplot_basics` (seeded) | `unnamed-chunk-40-1.png` | `8205022df91a30c7` | `8205022df91a30c7` | **MATCH** |
| `ggplot_basics` (seeded) | `unnamed-chunk-41-1.png` | `cce4a1edb9139c91` | `cce4a1edb9139c91` | **MATCH** |

Adding `set.seed()` — and nothing else — makes all four figures byte-identical across two
independent renders. This is direct causal proof, not correlation: unseeded RNG in the chapter's own
demo code (`rgamma()`/`project()` in `epidemic_models`; `geom_jitter()`/`geom_sina()` in
`ggplot_basics`) is the mechanism, and it is fixable with a one-line change to the source if the
project ever wants these two chapters' figures to be reproducible. The throwaway trees used for this
test were deleted afterward; `render_sep18` was never touched (confirmed: `grep -c set.seed` against
it returns 0 both before and after).

**Consequence for the project:** the epiRhandbook is not byte-reproducible in its figures, on any
environment, because of unseeded RNG in its own demo code (confirmed by direct experiment for
`epidemic_models` and `ggplot_basics`; source-identified but not independently re-rendered for
`combination_analysis` and `ggplot_tips`, see the asset table above). That is a property of the
content, not of these images, but it bounds what any reproduction effort here can honestly claim.

## Instrumentation neutrality
Re-measured with `verify/diff_chapter_parsed.py` (the real-HTML-parser metric, not
`diff_chapter.py`'s regex tag-stripper — see "Independent verification" below for why that
matters), over **10 chapters**, widened from the original 3 to deliberately span every profile in
the book: table-heavy (`stat_tests`, `regression`, `tables_descriptive`), widget-heavy
(`time_series`, `interactive_plots`), plain (`basics`, `help`), and the slowest chapters
(`time_series` 48s, `ggplot_tips`/`ggplot_basics` 25s each, `epidemic_models` 19s). Each was
rendered in a **second, separate working copy** (`~/ae/render_p3_noinstr`, built the same way as
`render_p3` — `render_sep18` minus `html_outputs/` — with no `.Rprofile`/`capture_footprint.R`
present) and compared against the same chapter's output from the main instrumented pass
(`render_p3`):

| chapter | raw lines differing | parser-based similarity | hunks | explanation |
|---|---|---|---|---|
| `basics` | 2 | **1.0000** | **0** | `GLightbox({...})` JS key order, inside `<script>` |
| `help` | 2 | **1.0000** | **0** | same lightbox key-order effect |
| `time_series` | 6 | **1.0000** | **0** | lightbox key order + 1 htmlwidget random DOM id |
| `ggplot_tips` | 6 | **1.0000** | **0** | lightbox key order + htmlwidget random DOM id |
| `epidemic_models` | 10 | **1.0000** | **0** | lightbox key order + 2 `DT::datatable()` random DOM ids (id attribute + its JSON payload) |
| `ggplot_basics` | 22 | **1.0000** | **0** | lightbox key order + 5 `DT::datatable()` random DOM ids |
| `interactive_plots` | 26 | **1.0000** | **0** | 1 `plotly` htmlwidget random DOM id + its JSON payload |
| `regression` | 344 | **1.0000** | **0** | `DT` random DOM id + the `gt` random per-table CSS-scoping id cascading through a `<style>` block (same mechanism as "Independent verification" below) |
| `stat_tests` | 430 | **1.0000** | **0** | the same `gt` CSS-scoping-id cascade |
| `tables_descriptive` | 554 | **1.0000** | **0** | the same `gt` CSS-scoping-id cascade (multiple tables) |

Every one of the 10 scores **exactly 1.0000 with zero parsed hunks** — not just a high ratio, a
literal empty diff on the extracted text. None is raw-byte-identical (rechecked directly with
`diff`; every row above has a nonzero raw line count, confirmed by inspecting the actual diff
output for each), but every single raw difference, across all 10, traces to one of three known,
pre-existing, per-render-random sources — quarto's lightbox JS option serialization, an
htmlwidget's/`DT`'s randomly-generated DOM id (and the JSON payload that references it), or `gt`'s
random per-table CSS id — and all three live exclusively inside `<script>` tags, `<style>` tags, or
an HTML tag's `id`/`data-for` **attribute value**. `diff_chapter_parsed.py` is a real HTML parser
that only extracts text between tags and explicitly skips `<script>`/`<style>` content entirely
(attribute values were never visible to it in the first place) — so this is not a coincidence of
the score rounding to 1.0000; the parser structurally cannot see any of these three sources, by
construction, for any chapter. `capture_footprint.R` is not among these three sources anywhere:
the hook returns its input completely unchanged; its only effect is the side-effect file write to
`/p3/footprints/`, a path outside `/book` entirely. The main pass's results above use the
instrumented renders throughout (neutrality holds).

**Scope note: this table is a TEXT check only, not a figure check.** `epidemic_models` and
`ggplot_basics` both appear in it, scoring 1.0000 with zero hunks — that shows instrumentation does
not affect their page *text*, but says nothing about their *figures*, since
`diff_chapter_parsed.py` never looks at an image. Whether instrumentation affects figures — the
actual question a reviewer raised — is a different, later-added test: see "Task 1: settling
run-to-run vs. instrumentation" above, which compares figures directly between two identically-
instrumented trees and finds the same 4 figures differ regardless, settling it without this
confound.

## Cross-chapter filesystem contamination
The 66 chapter renders ran sequentially in one working copy (`render_p3`), so in principle a later
chapter could read something an earlier one wrote. Two separate mechanisms were checked.

**Cache: no project-level `freeze:` setting, but a hidden per-project execution mirror exists and
was confirmed write-only for THREE chapters (not generalized further).** `grep freeze _quarto.yml`
has no match — the project never opts into quarto's git-committable `_freeze/` reproducibility
cache, confirming the earlier claim in the specific sense it was made. But quarto also maintains a
**separate, always-present** internal mirror at `.quarto/_freeze/<chapter>/execute-results/html.json`
(+ a copy of that chapter's figures) regardless of the YAML setting — this exists here and is
updated on every render. Whether that update means "read from" or just "written to" matters, so it
was tested directly rather than assumed, for three chapters, not one:
- `age_pyramid`'s `Sys.Date()`-driven figure (see "Generated assets" above) has a **different byte
  size in the actual rendered output** than the one sitting in `.quarto/_freeze/` from before Phase 3
  started — only possible if the chapter genuinely re-executed rather than being served the cached
  result.
- `epidemic_models` and `ggplot_basics`, checked as part of the round-2 remediation's A/A test (see
  "Task 1" above): each chapter's `.quarto/_freeze/new_pages/<chapter>/execute-results/html.json`,
  inherited unchanged from `render_sep18` (sha256 `28505e57b3f4b895` / `7a21134336695f05`, dated
  2026-07-21), had a **different sha256 and a fresh mtime** (`730be72910d4370a` / `672f9242aedead7f`,
  2026-07-22) immediately after rendering — again only possible if both chapters genuinely
  re-executed.

**This is confirmed write-only for these three specific chapters, not proven for every chapter.**
The stated mechanism (`freeze:` unset in `_quarto.yml`, so quarto has no config telling it to read
from this cache for ANY chapter) applies project-wide and gives good reason to expect the same
behaviour everywhere, but only these three chapters have been directly observed to re-execute rather
than replay a cached result. Narrowed here rather than generalized past the actual evidence.

**Shared-path writes: one confirmed, contained.** Compared a full recursive listing (path, type,
size, mtime) of `render_p3` now against `render_sep18` (the pristine copy source, untouched since
before Phase 3 began — its own newest file dates from before Phase 3's render run). Excluding
`html_outputs/` (wholesale-different by design, out of scope) and `.quarto/` (covered above),
everything that changed or is new falls into exactly two expected buckets — `new_pages/**` (each
chapter's own `_files/` assets and, for the 18 non-book chapters, its own standalone `.html`; see
"render-location surprise" above) and 3 new root files (`.Rprofile`, `capture_footprint.R`,
`render_chapters.sh` — Phase 3's own documented instrumentation/driver, not chapter output) — with
**one exception**: `data/standardization/deaths_countryA.csv` and `deaths_countryB.csv` changed
mtime with **identical size and identical sha256** on both sides. Traced to
`standardization.qmd`: it reads both datasets from a static remote GitHub URL, then (lines 170-171)
`rio::export()`s them right back to that local path — the chapter's own tutorial content
demonstrating how to export a cleaned dataset, not a bug. `utils/`, `renv.lock`, `renv/`, the
`.Rproj` file, and `LICENSE.md` are all confirmed untouched (mtime still Sep 2024, unchanged since
the original content freeze). Checked whether any OTHER chapter could be affected by
`standardization.qmd`'s write: only `data_used.qmd` references the same two filenames anywhere in
`new_pages/*.qmd`, and it also loads them from the remote URL, never from this local path — so
nothing currently reads what `standardization.qmd` writes here. **No contamination materialized in
this render sequence**, but the write pattern itself is real: a chapter writing into a shared,
non-`_files` project path is exactly the mechanism this check was designed to catch, and it would
be a genuine risk if a future chapter read from that same local path, or if the exported content
were ever non-deterministic.

## Package footprints
**52 of the 66 OK chapters produced a footprint** (the other 14 — the 10 PART-divider stubs plus
`apply_functions`, `modeling`, `rstudio_advanced`, and — notably — the real book chapter
`errors` — contain **zero executable R chunks**, so knitr never runs for them and there is nothing
to capture; confirmed directly, `grep -c '^```{r' new_pages/errors.qmd` → 0. That's a genuine
result, not a gap: those chapters need no R packages at all to render).

- **344 distinct namespaces** loaded across all 52 chapters (`footprints.tsv`), of which 13 are
  base/recommended R itself (`base`, `compiler`, `datasets`, `grDevices`, `graphics`, `grid`,
  `methods`, `parallel`, `splines`, `stats`, `stats4`, `tools`, `utils`) rather than one of the 473
  `renv.lock` packages.
- **331 of the 473 locked packages were loaded by at least one chapter; 142 (30%) were never loaded
  by any chapter's render.**
- Per-chapter footprint size: min 20, median 72, max 139 packages (`footprints.tsv`).

**What this does and does not prove.** Every render above — text comparison, asset hashing, and
package-footprint capture alike — ran each chapter individually **inside the full, unmodified
project tree, on the full 473-package Phase 2 image**: same `_quarto.yml`, same `renv.lock`, same
`data/`/`utils/`, every other package still installed and importable. That proves every published
book chapter plus `index` (49 book chapters + index, the same 50 compared throughout this document)
**renders correctly on its own** (one `quarto render` invocation, not the whole book at once) — real
content, that is what Phase 3 was scoped to check, and it holds for all 50. The two excluded
chapters attempted alongside them, `gis` and `plot_continuous`, reproduce their own known,
pre-existing failures under this same standalone rendering (see Render outcomes above) — not a new
failure mode this per-chapter granularity introduced. It does **not** prove a
chapter would render correctly against a **reduced** image containing only the packages its own
footprint lists: a chapter's `loadedNamespaces()` footprint is an empirical record of what got
loaded when everything else was ALSO available, not a verified-sufficient package list — an
implicit base-package assumption, a transitive dependency `library()`-loaded incidentally by an
earlier line, or a namespace some other loaded package pulls in without the chapter ever asking for
it directly, would all be invisible here and could still break a genuinely minimal build. Testing
that is Phase 5's job (the per-chapter image split), not something this phase's renders establish.

## Files
- `render_chapters.sh` — the per-chapter render loop (runs inside the container). Also installs the
  footprint-capture hook itself: writes `.Rprofile` (unconditionally, so this is reproducible from a
  bare `render_sep18` copy plus this script and `capture_footprint.R` — no manual setup step
  required) and then PROVES it is active with a canary knit before the per-chapter loop starts,
  failing loudly (non-zero exit, before any chapter is rendered) if `capture_footprint.R` is missing,
  or if a fresh `Rscript` in this directory does not actually produce a footprint file. (Verified
  both failure modes directly: file missing, and file present-but-non-registering, each aborts with
  a `FATAL:` message and no chapters attempted.)
- `.Rprofile` — the one-line hook wiring (`if (file.exists("capture_footprint.R"))
  source("capture_footprint.R")`), now committed here — previously this existed only as an untracked
  file manually placed into the `render_p3` working copy, so the capture workflow could not be
  reproduced from the repo alone. `render_chapters.sh` also writes this same content itself (see
  above), so the two cannot drift apart silently.
- `capture_footprint.R` — the `loadedNamespaces()` capture mechanism (knitr document hook,
  documented in-file).
- `aggregate_footprints.py` — turns a directory of `capture_footprint.R`'s per-chapter
  `<chapter>.txt` dumps into `footprints.tsv`. Reproduces the committed `footprints.tsv`
  byte-for-byte from `~/ae/p3/footprints/` (verified: `diff` empty, identical sha256). Fails loudly
  if `<footprints_dir>/_hook_errors.log` exists (the hook itself threw for at least one chapter —
  verified this trips: induced a `_hook_errors.log`, confirmed non-zero exit), and asserts every
  chapter `render_log.tsv` marks `OK` either has a footprint or is on the explicit
  `ZERO_R_CHUNK_CHAPTERS` list (14 chapters independently confirmed, by grepping their `.qmd` for
  zero ```` ```{r ```` chunks, to need no packages — any OTHER `OK` chapter missing a footprint is now
  a hard error (verified this trips too: removed one chapter's footprint file, confirmed non-zero
  exit naming it). Usage:
  `python3 aggregate_footprints.py <footprints_dir> <render_log.tsv> <out_footprints.tsv>`.
- `compare_chapters.py` — individual-render page vs. `ref_p2_book` page, using `verify/diff_chapter.py`'s
  metric unchanged (imported, not copied). Adds content provenance (sha16/bytes/path columns, same
  `sha16` convention as `verify/manifest.tsv`: first 16 hex chars of sha256) and fails loudly
  (non-zero exit) if: fewer than 50 chapters produce a similarity score; a book chapter's rendered
  HTML is missing; or any non-allowlisted book chapter scores below `FLOOR` (0.95) — the allowlist
  (`transmission_chains`, `dates`, `directories`, `index`, `editorial_style`) names the chapters
  already known to vary run-to-run, so their tolerance is explicit, not silent. Usage:
  `python3 compare_chapters.py <render_p3_dir> <ref_p2_book_dir> <render_log.tsv> <results.tsv>`.
- `compare_assets.py` — sha256-hashes, and for any mismatch genuinely pixel-diffs with PIL, every
  file in each chapter's generated asset directory (`<chapter>_files/`) on both sides. One row per
  file (not per chapter): `pixel_diff_pct`/`pixels_differing`/`pixels_total` are inherently per-file,
  so they are real columns, not a per-chapter average. Every mismatch is checked against an explicit
  `ALLOWLIST` (a pointer to where the justification lives, not an asserted mechanism — an earlier
  version hardcoded a causal story per chapter as fact, and one of those stories was wrong; see "Task
  1" above) and any mismatch NOT on it fails the run (verified: induced both a corrupted-image and a
  valid-pixel-edit mismatch in an isolated sandbox, confirmed non-zero exit and an `UNEXPLAINED`
  classification in both cases, never touching `render_p3`/`ref_p2_book` themselves).
  The `ALLOWLIST` is keyed by **exact `(chapter, file path)`**, one entry per each of the 9 observed
  mismatches, each carrying its classification (`confirmed` vs `source-inspection-only`) and an
  evidence pointer. An earlier version keyed it by **chapter**, which waved through every file in a
  volatile chapter — 109 rows read "allowlisted" under that design versus 9 now, and a corrupted new
  asset inside an already-volatile chapter would have passed. Verified by inducing exactly that case
  (a pixel edit to a non-allowlisted file inside an allowlisted chapter): exit 1, named as
  unexplained. Non-image files
  (`.js`/`.css`/`.json`/anything else) are hash-compared and reported separately from images (`kind`
  column) — in the current dataset there are zero of them (every htmlwidget payload here is inlined
  into the chapter's own HTML, never written to `_files/`), so this path is implemented but not
  exercised by real data. The 49 book chapters are derived from `ref_p2_book/new_pages/*.html`
  itself, not a separately-maintained list. Usage:
  `python3 compare_assets.py <render_p3_dir> <ref_p2_book_dir> <assets.tsv>`.
- `compare_widgets.py` — extracts every inline `<script type="application/json"
  data-for="htmlwidget-...">` payload from each compared page on both sides, normalizes the random
  per-render identifiers (the htmlwidget DOM id, and plotly's separate internal `"cur_data"` key —
  see "Inline widget payloads vs. book" above for why both, and how the second one was found), and
  compares what remains, position-matched. Reports payload counts, matches, and any genuine
  difference per chapter. Four gates fail the run (`sys.exit(1)`): a missing page for a book chapter;
  a per-chapter widget-count mismatch (always fatal, never allowlistable); a payload difference not
  on the `ALLOWLIST`; and a structural assertion of `EXPECTED_WIDGET_PAIRS = 175`. The `ALLOWLIST` is
  keyed by **`(chapter, widget_index)`** — index rather than payload hash, because widgets are
  emitted in fixed document order by the same source every render, the same principle that justifies
  filename-pairing for figures. Verified by inducing an unallowlisted payload edit: exit 1, named.
  An earlier version collected differences, printed them, and exited 0 regardless. Usage:
  `python3 compare_widgets.py <render_p3_dir> <ref_p2_book_dir> <widgets.tsv>`.
- `footprints.tsv` — `chapter`, `n_packages`, `packages` (comma-separated, sorted).
- `results.tsv` — `chapter`, `status`, `seconds`, `similarity_vs_book`, `note`, `rendered_sha16`,
  `ref_sha16`, `rendered_bytes`, `ref_bytes`, `rendered_path`.
- `assets.tsv` — one row per file: `chapter`, `path`, `kind` (image/non-image), `status`
  (match/mismatch/render-only/ref-only), `render_bytes`, `ref_bytes`, `render_sha16`, `ref_sha16`,
  `dimensions_match`, `pixel_diff_pct`, `pixels_differing`, `pixels_total`, `allowlisted`,
  `classification`.
- `widgets.tsv` — one row per widget payload: `chapter`, `widget_index`, `render_widget_id`,
  `ref_widget_id`, `payload_bytes_render`, `payload_bytes_ref`, `match`, `note`.

Machine-readable evidence also lives on compute at `~/ae/p3/`: `render_log.tsv` (raw render
outcomes before the similarity merge), `results.tsv`, `footprints.tsv`, per-chapter render logs in
`~/ae/p3/logs/`, and the raw per-chapter `loadedNamespaces()` dumps in `~/ae/p3/footprints/`. The
round-2 A/A test trees (`~/ae/aa_run1`, `~/ae/aa_run2`) and their per-chapter evidence
(`~/ae/aa1_evidence/`, `~/ae/aa2_evidence/`) also live on compute; the seeding-verification trees
were throwaway copies, deleted after use as documented in "Task 1" above.

## Independent verification, and a bug found in the measuring tool

The similarity numbers above were re-checked against the raw HTML with a **real HTML parser**
instead of `verify/diff_chapter.py`'s regex tag-stripper. That confirmed the classification above
and exposed a defect in the tool itself.

`diff_chapter.py` strips markup with `<[^>]+>`, which assumes a `>` inside a tag always ends that
tag. It does not. In a standalone render, quarto leaves the gt table `id` attribute unescaped:

```html
<th id="<strong>Characteristic</strong>" class="gt_col_heading ...">
```

The regex stops at the `>` of the embedded `<strong>`, so the rest of the tag leaks into the
extracted text. The book render escapes the same attribute, so only one side leaks — which makes an
invisible, CSS-internal attribute look like a large content change.

Re-measured with `verify/diff_chapter_parsed.py`:

| chapter | `diff_chapter.py` | parser-based | differing hunks |
|---|---|---|---|
| `stat_tests` | 0.9740 | **0.9987** | 1 — the navbar, nothing else |
| `regression` | 0.9863 | **0.9993** | 1 — the navbar, nothing else |
| `transmission_chains` | 0.9897 | **0.9896** | many — real value changes, as classified |

This is a **discriminating** check, not a confirming one: the same tool that collapses the two
artifact cases to near-identical leaves `transmission_chains`' genuine `Nosocomial`/`Community`
count changes fully visible. The gt-table explanation is therefore verified, not merely plausible.

**The bias is always pessimistic.** The bug understates similarity, so it can never convert a real
difference into a false pass. The Phase 1/2 figures frozen in `verify/manifest.tsv` remain valid as
a regression bar; they simply understate true fidelity on the four gt-table chapters (`stat_tests`,
`regression`, `tables_descriptive`, `survey_analysis`). `manifest.tsv` is deliberately left as
generated, so the frozen evidence keeps its original provenance.
