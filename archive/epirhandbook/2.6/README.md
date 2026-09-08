# epirhandbook:2.6 — Phase 5a (de-risk sample): common + per-chapter split

Splits the epiRhandbook monolith (Phase 2's `epirhandbook:2.5`, 473 packages in one
image) into a shared `epirhandbook-common` image plus thin per-chapter images, on
the **same FROZEN 4.3.2 package stack** Phase 1-3 already verified. Package
**versions** do not move in this phase — only the image **topology** does. See
`PROJECT.md` §"Why 3, 5a and 5b are separate" for why that is the one variable
this phase is allowed to change.

The de-risk **sample** (5 chapters) proved the mechanism; the generator now
emits the **full catalog** — every book chapter Phase 3 compared (49
`new_pages` chapters + `index` = 50), read straight from
`../2.5/chapters/results.tsv`. The "Sample results" tables below are the
original 5-chapter evidence, kept as the proof the split renders identically
to the monolith. Every image name is codified in the generated `images.yaml` catalog
(see "Files"), never typed into a build command.

## The split

- **common set** = packages loaded by **>=38 of the 52 chapters** with a
  footprint in `../2.5/chapters/footprints.tsv` (Phase 3's empirical
  `loadedNamespaces()` capture). 38 is not a round number chosen in advance —
  it is the natural break in the frequency distribution (`frequency.tsv`, this
  script's own output):

  | chapters loading it | packages at that count |
  |---:|---:|
  | 52 | 20 |
  | 50 | 2 |
  | 42 | 3 |
  | 41 | 30 |
  | 40 | 3 |
  | 39 | 1 |
  | **38** | **6** |
  | 26 | 1 |
  | 25 | 1 |
  | ... | ... |

  65 packages cluster at counts 38-52 (gaps of at most 2 between consecutive
  values in that range); the next-most-frequent package then drops to 26 — a
  gap of 12, six times the largest gap inside the cluster. That is the break;
  38 is its floor. 10 of the 65 are base-R packages (`base`, `compiler`,
  `datasets`, `grDevices`, `graphics`, `grid`, `methods`, `stats`, `tools`,
  `utils`) that ship with R itself and need no installing; the other 55 are
  real `renv.lock` packages.

- **per-chapter delta** = that chapter's **full footprint** (not
  footprint-minus-common). Each chapter's Dockerfile installs its own full
  footprint on top of `common`; pak sees whatever `common` already installed
  at the exact locked version and skips it (`dependencies=FALSE` never
  re-solves, so a skip is a true no-op) — it only builds what's missing. This
  is what makes each chapter image **⊇ its footprint by construction**,
  without generate.py or any Dockerfile needing to reason about whether
  `common`'s own package set is itself a complete dependency closure.

- **closure expansion.** Neither the common set nor a chapter's footprint is,
  by itself, safe to hand to pak with `dependencies=FALSE` (required — see
  "Why pak needs dependencies=FALSE" below). A footprint is an EMPIRICAL
  `loadedNamespaces()` record (Phase 3), not a declared dependency graph: a
  package can be accessed via `pkg::fun()` without an eager `NAMESPACE`
  import, so a build-time-only dependency (a compiled package's `LinkingTo`
  header, or an Import a chapter's own content never exercises) can be
  entirely invisible to `loadedNamespaces()` while still being required to
  install the footprint's own packages from source. `generate.py` therefore
  closure-expands every target set (common, and each chapter's footprint)
  over `renv.lock`'s own `Requirements` graph — the SAME graph
  `../2.5/pak_install.R` already walks for the full 473-package install, just
  restricted to a subset here. Because closure-expansion only ever ADDS
  nodes, the closure is a superset of the seed footprint by construction —
  this is what makes "image ⊇ footprint" true by construction rather than by
  a separately-checked invariant.

  One concrete example this surfaced: `googlesheets4` is not itself in the
  common set (no chapter's own footprint loads it directly), but `tidyverse`
  IS in the common set, and `tidyverse` Imports `googlesheets4` — which this
  `renv.lock` pins from **GitHub**, not CRAN. So even a common set that looks
  CRAN-only from its raw 65 names reaches GitHub once closure-expanded, and
  every image (common and every chapter, since they all build on common)
  needs the `GITHUB_PAT` BuildKit secret for exactly this one package.

## Why pak needs `dependencies=FALSE` (inherited from Phase 2, unchanged)

pak's SAT solver rejects an archived CRAN pin whose CURRENT release now needs
R >= 4.4, even though this image is frozen at R 4.3.2 (see
`../2.5/pak_install.R`'s own header for the full story — this is Phase 2's
trap, not a new one). The fix there was a topological **layered** install
with `dependencies=FALSE` per layer, built from `renv.lock`'s own
`Requirements` field. `pak_install_subset.R` (this directory) reuses that
exact mechanism, restricted to a subset: given an already-closure-complete
target list, it re-verifies the closure (a cheap self-check — see the
script's own header), subsets `renv.lock$Packages` to those names, and
installs them in the same topological layers.

## Build context

Each Dockerfile expects the **`epirhandbook/2.6/` directory itself** as the
build context (not its own subdirectory), so it can `COPY renv.lock`,
`COPY pak_install_subset.R`, and `COPY common/packages.txt` /
`COPY chapters/<chapter>/packages.txt` — one shared `renv.lock` and installer
script rather than duplicating a 155 KB file into every chapter directory.
Build from `epirhandbook/2.6/`:

```bash
DOCKER_BUILDKIT=1 docker build --secret id=github_pat,src="$HOME/.ghtoken" \
  -f common/Dockerfile -t epirhandbook-common:2.6 .

DOCKER_BUILDKIT=1 docker build --secret id=github_pat,src="$HOME/.ghtoken" \
  -f chapters/basics/Dockerfile -t epirhandbook-basics:2.6 .
# ... one -f/-t pair per chapters/<chapter>/Dockerfile
```

The `-t` image name is **`epirhandbook-<chapter>:2.6`** (chapter in the name,
version only in the tag; source underscores kept, e.g.
`epirhandbook-tables_descriptive:2.6`). Do not hand-type it — read it from the
generated `images.yaml` catalog, so the name is a generated artifact, not a
build-command string. (The de-risk
sample used `epirhandbook-2.6-<chapter>:2.6` — version in both name and tag;
that scheme is replaced.)

`renv.lock` here is a byte-identical copy of `../2.5/renv.lock`
(`generate.py` asserts this with a sha256 check on every run) — copied, not
symlinked, so this directory rsyncs to a build host as a self-contained
whole, the same way `epirhandbook/2.5` already does.

**BASE_IMAGE / digest pinning.** Both `common/Dockerfile` (`FROM
rbase:4.3.2`) and each chapter Dockerfile (`FROM epirhandbook-common:2.6`) use
a floating local tag via `ARG BASE_IMAGE=...`, mirroring
`../2.5/Dockerfile`'s own pattern exactly. A real digest pin (`FROM
name@sha256:...`) was considered but is not practical yet: Phase 4's
first-ever GHCR publish of `rbase` has still never been run (`PROJECT.md`
§3), so there is no portable, registry-backed digest to pin against.
compute's own local test registry (`localhost:5000/rbase@sha256:...`, used
for Phase 4's rehearsals) is deliberately NOT used here — it is a
host-specific throwaway, not a real published reference, and hard-coding it
would silently break on any other build host. Once `rbase` and
`epirhandbook-common` are published to GHCR, `ARG BASE_IMAGE` is the override
point, exactly as `../2.5/Dockerfile`'s own comment documents.

## Files

- `generate.py` — reads `../2.5/chapters/footprints.tsv`,
  `../2.5/chapters/results.tsv`, and `../2.5/renv.lock`, computes the common
  set and every target chapter's closure, and writes `renv.lock`,
  `frequency.tsv`, `images.yaml`, `common/{packages.txt,Dockerfile}`, and
  `chapters/<chapter>/{footprint.txt,packages.txt,Dockerfile}` for every book
  chapter Phase 3 compared (the 50 rows of `results.tsv` with a
  `similarity_vs_book` score — 49 `new_pages` chapters + `index`).
  Deterministic — every list is sorted before writing, nothing depends on
  wall-clock or filesystem iteration order. Verified by running it twice and
  diffing sha256 sums of every generated file: byte-identical.
- `images.yaml` — the ONE index, in Phase 4 catalog schema (`name`, `dir`,
  `tags`, `base`, `base_digest`, `live`, `frozen`), a row per image: `common`
  (row 0) then the 50 chapters. The Phase 4 planner consumes it directly, so
  the image names are a generated artifact, never reconstructed by hand. The
  chapter↔image linkage lives here with no dedicated field and no second store:
  `name` is the lowercased image, and the basename of `dir` is the original-case
  chapter (`name: epirhandbook-transition_to_r` ↔ `dir: …/chapters/transition_to_R`).
  Validated against Phase 4's own `plan.validate_catalog`.
- `pak_install_subset.R` — the installer, adapted from `../2.5/pak_install.R`
  (see its own header for the full adaptation rationale).
- `common/packages.txt` / `chapters/<chapter>/packages.txt` — the
  closure-expanded install target for that image's own layer (what
  `pak_install_subset.R` actually installs).
- `chapters/<chapter>/footprint.txt` — that chapter's RAW footprint from
  `footprints.tsv`, filtered to real `renv.lock` names (base-R names
  dropped). This is the list the "package-set correctness" check below is
  measured against — a strict subset of `packages.txt`.
- A book chapter with **no** `footprints.tsv` row (Phase 3 captured zero
  loaded packages — a prose-only page such as `errors`) gets **only** a bare
  `chapters/<chapter>/Dockerfile`: `FROM epirhandbook-common:2.6` with no
  install delta, no `footprint.txt`, no `packages.txt`. Its image is common
  re-tagged under the chapter's own name, present so every book chapter has a
  correspondingly-named image to render on.
- `frequency.tsv` — `package`, `n_chapters`, `of_52`, `in_common` for all 344
  distinct packages `footprints.tsv` names. The distribution cited above.

## Sample results (5 chapters, built and verified on compute)

| | common | basics | epicurves | interactive_plots | tables_descriptive | time_series |
|---|---:|---:|---:|---:|---:|---:|
| footprint (raw, renv.lock names) | -- | 53 | 67 | 64 | 101 | 127 |
| own closure (install target) | 125 | 121 | 152 | 127 | 181 | 207 |
| delta over common | -- | 3 | 27 | 2 | 56 | 82 |
| image size | 2.89 GB | 2.89 GB | 3.0 GB | 2.9 GB | 3.1 GB | 3.31 GB |
| `installed.packages()` count | 149 | 152 | 174 | 151 | 202 | 226 |

(`installed.packages()` always counts more than the explicit install target,
in every image including Phase 2's own 473-package monolith — 489 vs 473
there — because it also reports R's own bundled base+recommended packages,
present in any R installation regardless of what pak installs. The
authoritative "did the RIGHT packages install at the RIGHT version" check is
the build-time invariant below, not this raw count.)

**Package-set correctness** (raw footprint, i.e. `chapters/<chapter>/footprint.txt`,
not the larger closure — run directly against the built image, independent of
the Dockerfile's own build-time check, which validates the closure):

```
basics               (53 footprint packages): FOOTPRINT CHECK OK: all 53 raw-footprint packages load at exact locked version
epicurves            (67 footprint packages): FOOTPRINT CHECK OK: all 67 raw-footprint packages load at exact locked version
interactive_plots    (64 footprint packages): FOOTPRINT CHECK OK: all 64 raw-footprint packages load at exact locked version
tables_descriptive  (101 footprint packages): FOOTPRINT CHECK OK: all 101 raw-footprint packages load at exact locked version
time_series         (127 footprint packages): FOOTPRINT CHECK OK: all 127 raw-footprint packages load at exact locked version
```

**Render + compare vs. the Phase 3 monolith render**, using the Phase 3
comparators (`../2.5/chapters/{compare_chapters.py,compare_assets.py,compare_widgets.py}`)
completely unchanged (sha256-verified identical to the committed copies
before use) against a chapter-filtered copy of `ref_p2_book` (read from, never
written) — full output in `verify/{results,assets,widgets}.tsv`:

| chapter | similarity vs. book (this run) | Phase 3 monolith's own number | match |
|---|---:|---:|---|
| basics | 0.9997 | 0.9997 | exact |
| epicurves | 0.9996 | 0.9996 | exact |
| interactive_plots | 0.9977 | 0.9977 | exact |
| tables_descriptive | 0.9945 | 0.9945 | exact |
| time_series | 0.9996 | 0.9996 | exact |

All 5 match Phase 3's own recorded per-chapter similarity to 4 decimal
places. 4 of 5 chapters' rendered byte counts are exactly identical to Phase
3's monolith render (`basics` 233960, `epicurves` 319928, `tables_descriptive`
339137, `time_series` 262758 bytes); `interactive_plots` differs by 9 bytes
(201650 vs 201659) despite an identical similarity score — consistent with
the same per-render-random noise (a random htmlwidget/plotly id of variable
digit count) Phase 3's own README already documents as invisible to this
metric.

`compare_assets.py` (figures): **55/55 images matched, 0 mismatches, exit 0**
— every figure across all 5 chapters is byte-identical to its Phase 3
monolith counterpart. None of these 5 chapters is on Phase 3's
known-run-to-run-volatile list (`epidemic_models`, `ggplot_basics`,
`combination_analysis`, `ggplot_tips`, `transmission_chains` — see
`../2.5/chapters/README.md`), so a clean 0-mismatch result is exactly what
was expected, not a coincidence.

`compare_widgets.py` (inline htmlwidget/DT/plotly payloads): of the 16 real
widget pairs across these 5 chapters (`epicurves` 5, `interactive_plots` 6,
`tables_descriptive` 4, `time_series` 1, `basics` 0), **16/16 matched, 0
mismatches, no chapter with a differing widget count**.

**Exit codes, and why two of the three are non-zero on a 5-chapter sample.**
`compare_chapters.py` and `compare_widgets.py` both hard-code an EXPECTED
total sized for the FULL Phase 3 run (`EXPECTED_BOOK_CHAPTER_COUNT = 50`,
`EXPECTED_WIDGET_PAIRS = 175`) as a module-level constant, not a CLI
parameter — deliberately, so a chapter silently going missing from a real
50-chapter run is caught. Pointed at a genuine 5-chapter sample, both
assertions necessarily fire (5 != 50, 16 != 175): this is a **structural**
consequence of "use the comparators UNCHANGED against a partial sample," not
a quality signal. `compare_widgets.py` additionally reports chapter `index`
as having a missing ref page: its own chapter list unconditionally appends
`index` regardless of the sample under test, and `index` is deliberately
excluded from this run's `ref_subset` (it is not one of the 5 sample
chapters). `compare_assets.py` has no such hard-coded total (only "any
mismatch not on the allowlist fails"), which is why it alone exits 0 on this
sample — a genuine, unconditional pass, not one that a structural count
artifact happens to spare.

| comparator | exit code | why |
|---|---:|---|
| `compare_chapters.py` | 1 | solely `len(sims)=5 != EXPECTED_BOOK_CHAPTER_COUNT(50)` — structural |
| `compare_assets.py` | 0 | genuine pass — 55/55 matched |
| `compare_widgets.py` | 1 | `total_pairs=16 != EXPECTED_WIDGET_PAIRS(175)` (structural) + `index` page-missing (structural: `index` is not in this sample) |

## Scaling up (done)

The target chapter set is no longer a hand-maintained list. `generate.py`
derives it from `../2.5/chapters/results.tsv` (`read_scored_chapters`: every
row with a non-empty `similarity_vs_book`) — the full catalog of 50 book
chapters Phase 3 compared (49 `new_pages` + `index`). The de-risk sample was
the five representative chapters `time_series` (heaviest, htmlwidgets),
`tables_descriptive` (gt/gtsummary tables), `interactive_plots` (plotly),
`epicurves` (ggplot-heavy), and `basics` (plain); those are now simply five
of the fifty. The common-set derivation still runs over all 52
`footprints.tsv` rows regardless — it is a property of the whole book, not of
which chapters get their own image — so nothing about the common-set logic
changed in the scale-up. Re-running `generate.py` reproduces the full set
byte-identically.
