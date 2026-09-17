# PROJECT.md — aedockerpublic / epiRhandbook stabilization

Working notes and understanding checklist for this repo. Not published: this file is excluded
from git via `.git/info/exclude`, because `appliedepi/aedockerpublic` is a public repo.

---

## 1. The problem

`github.com/appliedepi/aedockerpublic` will host the Docker images for Applied Epi products.
The first job is to stabilize **epiRhandbook**, which had not compiled for a long time.

The cause is a tightly pinned 2024 stack that no longer matches any current default toolchain:

- The handbook pins **R 4.3.2**, **Bioconductor 3.18**, **Quarto CLI 1.4.550**, on **Ubuntu jammy**.
- Its `renv.lock` pins **473 packages** (463 CRAN + 3 Bioc + 7 GitHub).
- `ggtree`/`treeio` need Bioc 3.18, which hard-couples the build to R 4.3.
- Each chapter loads its own packages with `pacman::p_load()`. When renv is not restored, `p_load`
  reaches live CRAN and installs whatever is current today. That silently breaks the pinned stack.
- The build uses **Quarto + babelquarto** (9 languages), not bookdown.

The strategy is: reproduce the old environment exactly so the **unchanged** content renders, and
only then modernize.

## 2. Which content, and which reference

Two different versions of the handbook content exist. Do not mix them.

| Content | Where | Role |
|---|---|---|
| **Sep-18-2024** (`epiRhandbook_eng` commit `c3cbc76`) | live at `https://www.epirhandbook.com/en/` | **The frozen baseline. This is what we reproduce.** |
| **Jan-2025 drift** (branch `richard` @ `e121efa`, and `deploy-preview`) | published nowhere | **Parked.** A 52-chapter unpublished content update. Reviewed only at the very end to salvage anything useful. |

The reproduction target is a **fresh crawl of the live site**, not the `html_outputs/` committed in
the repo. The committed output is stale, so it is not a valid reference.

- Live crawls on compute: `~/ae/live_crawl` (English) and `~/ae/live_crawl_ml/<lang>` (7 languages).
- Sep-18 render source on compute: `~/ae/render_sep18`.
- The regression bar is `epirhandbook/2.5/verify/manifest.tsv` — per-page text similarity plus a
  `sha16` content hash. Regenerate it with `epirhandbook/2.5/verify/make_manifest.py`.

**The manifest means "same output" only when package versions match.** It is the bar for Phase 2
and Phase 3. It is **not** the bar for Phase 5, where newer packages legitimately render differently.

## 3. Phase roadmap and status

One variable changes per phase. Every phase after Phase 1 is regression-tested against Phase 1's render.

| Phase | What changes | Status |
|---|---|---|
| **1 — Bare reconstruct** | `rocker/r-ver:4.3.2` + sysdeps + Quarto 1.4.550 + `renv::restore()`. No custom base, no pak. Establishes the known-good baseline render. | **Done** — commit `017fdbe` |
| **2 — Factor + pak rehearsal** | Split into `rbase/4.3.2` + `epirhandbook/2.5`; swap `renv::restore()` → **pak**, driven by the exact same lock pins. Must render identical to Phase 1. | **Done** — commits `bfec633`, `59ed133` |
| **3 — Per-chapter rendering** | Render each chapter **individually** on the full 473-package image. Only the render *granularity* changes, not the package set. Capture each chapter's real package footprint. | **Done** — codex passed on round 6 |
| **4 — Productionize** | `images.yaml` catalog, manifest-driven CI (selective + cascade + nightly), publish to GHCR, optional SSH runtime toggle. Same content, same two images. | **Code complete, codex PASS on round 8, committed local `1dd7960`. NOT yet pushed/published.** Rounds 1-7 each found a real supply-chain or schema defect; the parser was replaced by hash-pinned PyYAML + a strict schema after four rounds of hand-rolled-reader divergences (see §8). The first-ever GHCR publish fires on the first push to main and needs Richard's explicit go. `GH_READONLY_PAT` is OPTIONAL (build works tokenless; the PAT only lifts the anonymous GitHub API rate limit for the 7 GitHub-pinned packages) — add it only if a CI run actually hits the limit. |
| **5a — Split, same packages** | Build `epirhandbook-common` + 50 thin per-chapter images, on the **frozen 4.3.2 stack**. Package versions do not move. | **Done** — codex PASS round 5, committed `beec92f`, unpushed |
| **5b — Modernize** | Modern `rbase/4.6.0` + minimal forward-port of the frozen content to 2026 packages, published as **2.7**. Topology does not move. | Not started |

**Repo state:** pushed. `origin/main` is at `e119c7f`; local and remote in sync. Note that the push
bypassed a branch-protection rule on `appliedepi/aedockerpublic` ("Changes must be made through a
pull request") — admin permissions allowed it, and GitHub recorded it as a bypass. Decide whether
future work on this repo should go through a PR instead.

### Why 3, 5a and 5b are separate

Each asks a different question, and separating them is what makes a failure attributable.

- **Phase 3** asks *"can a chapter render alone?"* — answered on the monolith, so the package set is
  not a variable.
- **Phase 5a** asks *"can a chapter render on a minimal package set?"* — answered on the frozen
  4.3.2 stack, so the package **versions** are not a variable. A failure here means the footprint
  was wrong, and nothing else.
- **Phase 5b** asks *"does this content still work on 2026 packages?"* — answered without moving the
  topology again.

**Phase 5 was originally one phase, and that was a mistake.** It changed two major variables at once:
package versions (2024 → 2026) *and* image topology (one monolith → ~50 thin images). A chapter
failing to render would have been ambiguous — a wrong footprint, or a package that changed
underneath it, with no way to tell which.

The ordering matters as much as the split. **5a must come before 5b**, because 5a's success bar is
"renders identically to the Phase 3 monolith render", and that frozen reference only exists while
the packages are still pinned at 4.3.2. Modernize first and the reference is gone, so the footprints
would ship having never been tested against anything.

### Success bars

| Phase | Bar |
|---|---|
| 5a | Each chapter renders on its minimal image **identically to its Phase 3 monolith render**, measured by the Phase 3 comparators (`compare_chapters.py`, `compare_assets.py`, `compare_widgets.py`) unchanged. |
| 5b | **Size of the source diff** — as few changes as possible. NOT output equivalence: two years of newer packages render differently, and where an API changed the source must change. |

## 4. Design decisions, and why

- **`rbase`, not `base`.** The name leaves room for a separate `pythonbase` later, and it matches
  the existing `ghcr.io/niphr/cs/rbase`.
- **`rbase:4.3.2` is fully self-owned.** `FROM ubuntu:jammy` (digest-pinned) + R 4.3.2 from **Posit
  r-builds**, with **no rocker**. Control and consistency over lower maintenance.
- **openblas 0.3.20 is installed deliberately.** It is the exact BLAS that rocker links. Matching it
  is why dropping rocker moved no computed numbers. A different BLAS would have shifted values
  across many chapters.
- **pak is driven by the lock, and chooses nothing.** `renv.lock` stays the single source of truth.
  The installed version is always the pin; the *ref form* only changes how each package is fetched.
- **CRAN is `cloud.r-project.org` source, not PPM.** Phase 2 restores a lock whose pins span many
  dates, so no single PPM snapshot contains them all. Only cloud carries every archived version.
- **`GITHUB_PAT` is a BuildKit secret.** Never `--build-arg` + `ENV`, which would bake the token
  into the image's `Config.Env` and leak it on `docker inspect` or push.

## 5. Traps already found (do not re-derive)

- **pak's SAT solver versus R 4.4.** A naive `pkg@version` ref fails for 15 packages. pak evaluates
  the *current* release's R constraint even when an *older* version is pinned, and reports a spurious
  dependency conflict. The fix is `url::` refs pointing straight at the CRAN Archive tarball, which
  bypasses the solver. renv never hits this, because renv does not solve — it just installs the pin.
- **pak install ordering.** `dependencies = FALSE` resolves cleanly but drops build-order edges, so
  a source package races its own build dependency (RcppRoll built before Rcpp). `dependencies = NA`
  restores order but re-activates the solver. The fix is a **topological layer install**: build the
  graph from the lock's own `Requirements`, Kahn-sort into 15 layers, install each layer with
  `dependencies = FALSE`.
- **Bioconductor drift.** The lock pins `ggtree` 3.10.0, but Bioc 3.18's live contrib directory now
  serves 3.10.1. Only the Bioc Archive still has 3.10.0.
- **pak leaves about 4 GB of build scratch in `/tmp`.** Delete it in the *same* `RUN` layer, or the
  image doubles in size (9.5 GB → 5.1 GB).
- **Docker tag races.** Two builds tagging the same image name: last to finish wins, so a bad build
  can clobber a good one. Serialize builds that share a tag.
- **Two render failures are not the image's fault.** `plot_continuous` never calls
  `library(tidyr)`, and it is an unused `.qmd`. `gis` fetches live OpenStreetMap tiles at render
  time, which aborts the whole book, so it is commented out of `_quarto.yml` for rendering.
- **Render into a writable copy.** `render_book()` deletes `html_outputs` first.
- **Linux needs the filename-case shim.** Run `python3 fix_image_case.py <source>` before rendering.

## 6. How we work on this

- **Build on compute.** bench has no Docker. Rsync the build context to `compute:~/ae/ehb_build`,
  then `docker build` over SSH.
- **Verify the built image, not the Dockerfile.** After every build, run
  `docker inspect <img> --format '{{.Config.Env}}'` to confirm no token was baked in. A
  source-only review, codex included, does not catch a baked-in secret.
- **Execution model:** opus orchestrates and writes the brief, sonnet implements, a *fresh* sonnet
  re-runs the objective check and returns raw evidence, opus makes the call.
- **codex is the phase gate.** A phase is done only on codex sign-off. codex attacks soundness
  ("what is not really pinned"), not the render, which is objective and already measured.
- **The gate is per phase, not per build iteration** — Claude owns the tight loop, and the codex
  quota is spent deliberately.

---

---

## 7. The historical record

`CHANGELOG.md` holds it: the phase 4 productionize log, the 2.8 addendum for the GIS chapter's
return, and the 2.9 addendum for the per-language layout. Those describe the project as it was
at the time of writing, not as it is now.

---

## 8. Understanding checklist

Things Richard should be able to explain without looking them up. Tick when demonstrated.

### The problem and its branches
- [ ] Why the handbook stopped compiling, naming the specific coupling that freezes it at R 4.3.
- [ ] What `pacman::p_load()` does per chapter, and why that is dangerous without a restored renv.
- [ ] The difference between the Sep-18 frozen content and the Jan-2025 drift, and which is live.
- [ ] Why the committed `html_outputs/` is not a valid reference, and what replaced it.

### The solution and its design decisions
- [ ] Why each phase changes exactly one variable, and what that buys when something breaks.
- [ ] How pak is made to obey `renv.lock` exactly, and why the ref *form* varies per package.
- [ ] The pak solver trap: why `pkg@version` fails for an archived pin in 2026.
- [ ] The pak ordering trap: why neither `dependencies = FALSE` nor `NA` works alone.
- [ ] Why the topological layer install is correct, and what renv does internally that mirrors it.
- [ ] Why openblas 0.3.20 specifically, and what would have gone wrong with a different BLAS.
- [ ] Why a secret must be a BuildKit secret, and how to prove a token did not leak into an image.
- [ ] Why the manifest is a valid bar for Phase 2 and 3 but not for Phase 5.
- [ ] Which pages are known-volatile in the render diff, and why each one moves.

### The broader context
- [ ] What Phase 3's per-chapter footprints are *for*, and why they beat static scanning.
- [ ] Why Phase 3 and Phase 5 are separate, in terms of which variable each isolates.
- [ ] What `images.yaml` cascade means, and when a nightly build differs from a selective build.
- [ ] What "archival-grade" would require beyond today's build (the hardening TODO list).
- [ ] Why Phase 5's success metric is source-diff size, not output equivalence.

### Phase 4 — supply-chain controls (§8)
- [ ] Why a job-level ref guard in the workflow itself is needed even though `build.yml`
      already filters `on: push: branches: [main]`, and how it fails when dispatched off `main`.
- [ ] Why `nightly.yml` had to lose `packages: write` entirely, not just its push step, and
      what "the absence of the capability is the control" means concretely.
- [ ] Why "the build succeeded" already proves "all 473 locked package versions still resolve"
      for `epirhandbook` specifically — where that check actually lives.
- [ ] Why nightly does NOT attempt a live-site render comparison, and what would be needed to.
- [ ] What `frozen: true` prevents, and the exact override path when a republish is genuinely intended.
- [ ] Why vendoring a narrow YAML reader was chosen over hash-pinning `pyyaml` at first — and
      why that choice was later reversed (§8.9): what "bounded" vs "unbounded" means for a
      parser's own correctness contract, concretely.
- [ ] Why an unknown `base:` name and a cycle used to look identical to the planner, and how the
      fix tells them apart.
- [ ] Why the concurrency group must not include `${{ github.ref }}`.
- [ ] What the `publish` GitHub Environment does and does not do until a required reviewer is
      configured, and where that's configured.
- [ ] The residual risk of allowing direct pushes to `main`, and why CODEOWNERS + the `publish`
      environment don't fully close it.

### Phase 4 round 2 — token privilege and parser strictness (§8.8)
- [ ] Why a `packages: write` job must not feed its own `GITHUB_TOKEN` into arbitrary
      package-build code, even though that same token is legitimately needed for
      `docker/login-action` and `docker push` in the SAME job.
- [ ] What happens when `GH_READONLY_PAT` is not configured as a repository secret, and why
      that is safe (no fallback to a write-capable token) rather than merely "usually fine."
- [ ] Why the frozen-tag check moving before `docker build`/login is a real security property
      (shortens the window a credential is live), not just a speed optimization.
- [ ] The `live: False` bug specifically: why a silently-accepted wrong-cased boolean is worse
      than a parse error, in terms of what it does to the catalog's meaning.
- [ ] Why `["a,b"]` must stay one tag, not two, and why a trailing comma must error rather than
      insert a null.
- [ ] Why an unknown per-image key has to be a hard error, given that `plan.py` already defaults
      `live`/`frozen` when they're absent.

### Phase 4 round 3 — vendored-parser reversal (§8.9)
- [ ] Why four rounds of adversarial review blocking on the same "how do we read images.yaml"
      question is a pattern, not bad luck — what made the vendored reader's contract unbounded.
- [ ] Why `validate_catalog()`'s allowlist schema is bounded where the hand-rolled parser was
      not, even though PyYAML resolves strictly MORE implicit-scalar forms than the vendored
      reader ever recognized.
- [ ] How `tags: [2024-01-01]` gets rejected without `validate_catalog()` needing to know PyYAML
      turns it into a `datetime.date` — what property of the schema makes that automatic.
- [ ] Why hash-pinning PyYAML closes round 1's ORIGINAL finding correctly, where vendoring only
      avoided it — and what `--require-hashes` actually refuses if a hash doesn't match.
- [ ] Why `TestValidateCatalog` drives real YAML strings through `yaml.safe_load()` rather than
      calling `plan.validate_catalog()` on a hand-built Python dict directly.
