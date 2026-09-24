# CHANGELOG — aedockerpublic / epiRhandbook image lines

The historical record of this project: what each image line changed, and why. Newest first.

Split out of `PROJECT.md` on 2026-09-17, which was then deleted: its standing material moved
to `README.md` and everything historical came here. Every entry below describes the project AS
IT WAS when it was written, and later work has changed some of it. Read it as a record, never
as current documentation.

---

## 2.9 addendum (2026-09-24): an unquoted language code `no` stays a code

- [ ] **`build_all_chapters.sh` read `languages.yml` with `yaml.safe_load`.** That reads an unquoted `no` as False, so a Norwegian `code: no` stopped the build with "every languages[] entry needs a 'code'". `read_languages` now uses `yaml.BaseLoader`, which keeps every scalar a string. On the handbook's current `languages.yml` it prints the same two lines as before.
- [ ] **`inject_language_links.R` read the same file with plain `yaml.load_file`.** `code: no` became the text "FALSE", and the injector skipped that language without an error: "8 of 9 declared language(s)". It now passes handlers that keep yes, no, on, off, y, n, true and false as text. On a 16-page fixture from the handbook's staging site, the old and new injectors write identical pages for the current language list. With `code: no` added, the new one links `../no/basics.html` on every page.
- [ ] **The code shape is still checked before the image runs.** The handbook's `build-deploy.yml` accepts only 2 or 3 lowercase letters for each code and for `main`, before it calls `build_all_chapters.sh`. `read_languages` itself checks presence only, as it did before.
- [ ] **What CI will do on push.** Both files are under `epirhandbook/2.9/common/`, so `epirhandbook-common` changes and every image built on it rebuilds.

## 2.9 addendum (2026-09-22): the workflows get a structural linter

- [ ] **`checks.yml` now runs actionlint over the workflow files.** Nothing looked at them before. The planner tests say nothing about `build.yml`, and the `yaml.safe_load` parse in the catalog validation cannot see a malformed `uses:` reference, a `needs:` edge to a job that does not exist, a shell fault, or an expression that cannot resolve. Both workflows passed clean on the day the step was added, under actionlint 1.7.7 with shellcheck 0.9.0 and 0.10.0, so the step arrived green rather than with a backlog behind it.
- [ ] **What actionlint does NOT do.** It does not verify that a `uses:` repository exists, only that the reference is well formed: a step naming a repository that was never published passes. It reads and never runs. Its shell coverage is whatever shellcheck's static rules catch, which is not "any shell fault".
- [ ] **The step asserts shellcheck is present.** actionlint disables its shellcheck rule when the binary is missing and still exits 0, so without the assertion the step would keep passing while silently covering less. shellcheck itself comes from the runner image and stays unpinned; actionlint is pinned by version and verified against the published SHA-256.
- [ ] **The lint gates publication, which took a second step to achieve.** `build.yml` has no `needs:` on `checks.yml`, and both fire on `push`, so on a push to main they run at the same time: a lint living only in `checks.yml` catches faults before a merge and stops nothing from reaching GHCR. The lint therefore also runs in `build.yml`'s `plan` job, which every build layer `needs:`. This is the same shape as a published site being built from a commit whose gate failed.
- [ ] **The lint is a script, not a pasted block.** `.github/scripts/lint_workflows.sh`, called from both places. The pinned version and its SHA-256 are one fact, and two copies of one fact can disagree: this repository already removed an instance of that shape when `groups.yaml` went, in the addendum below. The script is itself shellcheck-clean under 0.9.0 and 0.10.0.
- [ ] **`description` must now be ONE line.** The catalog header always promised "One line about the image", but validation only required a non-empty string, so a YAML block scalar passed. The check asks `splitlines()` what a line is rather than testing for `\n` and `\r`: an adversarial review found five separators reachable from ordinary double-quoted YAML escapes (U+000B, U+000C, U+0085, U+2028, U+2029) that a hand-written newline test misses and Python counts as line boundaries. Three tests cover it, including the accepting direction. An OCI label value MAY hold a newline; this is a presentation contract, not a format limit.
- [ ] **What CI will do on push.** `.github/scripts` and `.github/workflows` are both machinery directories, so `changed_images.py` reports every catalog image as changed and the run PLANS all nine. How many actually republish depends on execution: an image already carrying this SHA from an earlier partial run is skipped, and a failure in an earlier layer blocks the layers that depend on it. No catalog content changed.

---

## 2.9 addendum (2026-09-17): the layout becomes the group membership

- [ ] **What changed here.** All 50 per-chapter package lists moved out of
      `epirhandbook/2.9/chapters/<stem>/packages_cran.txt`. Each one now sits in the directory of
      the group image that renders its chapter, as
      `epirhandbook/2.9/groups/<group>/packages_cran_<stem>.txt`. `epirhandbook/2.9/chapters/` is
      gone. No byte of any list changed, and all seven generated lists are unchanged.
- [ ] **`groups.yaml` is deleted.** `generate_groups.py` discovers group membership from that
      layout instead of reading it from a file. The design rationale that file carried moved into
      the generator's header comment.
- [ ] **Why.** Two files stated one fact. `groups.yaml` assigned each chapter to a group, and
      `images.yaml` lists the chapters each group image renders. Two statements of one fact can
      disagree, and a reader cannot tell which one is true. The location of a package list now
      carries the assignment, and `images.yaml` is the one thing left to check it against.
- [ ] **The new check.** `generate_groups.py` compares the layout against each group image's
      `renders` list, group by group and in both directions. It runs in write mode and in
      `--check` mode, before any union is built. A global stem-set comparison would pass a chapter
      filed under the wrong group, so the comparison is per group.
- [ ] **Why that check cannot rely on the generated lists.** The `errors` chapter runs no R, so
      its package list is empty. Delete that list, or file it under the wrong group, and all six
      group lists and the monolith stay byte-identical. Only the membership check sees it.
- [ ] **Why the generator's two patterns anchor with `\A` and `\Z`, never `^` and `$`.** Python's `$` also matches immediately before a final newline, so `^content/en/(...)\.qmd$` accepts `'content/en/rmarkdown.qmd\n'`. A `renders:` entry written as a YAML block scalar produces exactly that value, and the membership check must reject it. `generate_groups.py:118` and `:120` carry a comment saying so. It is recorded here as well because the simplification is tempting and nothing would stop it: no committed test covers a block-scalar entry, so swapping the anchors back reintroduces the fault with every test still green. A test fixture would be the stronger guard, and `generate_groups.py` has no test suite at all, so that is its own piece of work.

- [ ] **Six Dockerfile comments.** Each group Dockerfile's header pointed at `groups.yaml` for its
      chapter membership. It now points at the `packages_cran_<stem>.txt` files beside it. No
      instruction changed.
- [ ] **Still stale after this change.** The header comment of `epirhandbook/2.9/images.yaml` and
      one comment in `.github/workflows/build.yml` still name `groups.yaml`. The next step of the
      same plan owns both.
- [ ] **What CI will do on push.** Each of the six group directories holds a changed Dockerfile
      and its chapters' package lists. `changed_images.py` reports all six images as changed.
      `rbase`, `epirhandbook-common` and `epirhandbook-monolith` are untouched.
      `generate_groups.py`, the two `README.md` files and the deleted `groups.yaml` all sit at the
      shared context root. None of them is a declared build input.

---

## 2.9 addendum (2026-09-10): the per-language layout

- [ ] **What changed here.** The 2.8 line was copied to `archive/epirhandbook/2.8/` and renamed to
      `epirhandbook/2.9/`. Every tag, `dir:`, `context:` and `ARG BASE_IMAGE` says 2.9. The nine
      image names, the six groups and all seven generated package lists are unchanged. The two
      workflows and the two test files now load `epirhandbook/2.9/images.yaml`.
- [ ] **Why.** The handbook moves every language into its own Quarto book project,
      `content/<lang>/`, with its own `_quarto.yaml` and one root `languages.yml`. The old layout
      is gone: no `chapters/<stem>.qmd`, no `.<lang>.qmd` infix, no root `_quarto.yml`, no
      `babelquarto` block. The image line has to carry the render scripts, so it moves first.
- [ ] **The render scripts.** `build_all_chapters.sh` reads `languages.yml`, renders
      `content/<lang>/<stem>.qmd` with the container's working directory set to that project, and
      assembles every language under `<lang>/` with a four-line redirect stub at the root.
      `inject_language_links.R` reads `languages.yml` and swaps the first path segment.
      `rewrite_lang_config.R` is deleted: each language project already declares its own language,
      so there is nothing left to rewrite.
- [ ] **`renders` entries.** Each one names the main-language file, `content/en/<stem>.qmd`. The
      stem is still the last path segment, so `plan.py --chapter-images` is unaffected.
- [ ] **brio.** `common/packages_cran.txt` still lists it. It was added for the deleted config
      rewriter, and no script in the image loads it now. Left in place so the package set does not
      change with this rewrite.
- [ ] **What CI will do on push.** `.github/workflows/` and `.github/scripts/` both changed, so
      `changed_images.py` reports every image as changed and all nine rebuild and publish under
      the `2.9` tags. The handbook still pulls `epirhandbook-common:2.8` in four places, so
      nothing on the handbook side moves until its own cutover.

---

## 2.8 addendum (2026-09-02): the GIS chapter returns

- [ ] **What changed here.** `gis` joined the `analysis` group. Its package list lives under
      `epirhandbook/2.8/chapters/gis/` (109 names: `loadedNamespaces()` of one executing render
      minus base R). `generate_groups.py` reads `epirhandbook/2.8/chapters/<stem>/` for a stem with
      no 2.7 directory, and refuses a stem present in both roots. Analysis list 227 -> 253 names,
      monolith 298 -> 320. `epirhandbook/2.8/images.yaml` lists `chapters/gis.qmd` under analysis.
- [ ] **Why not under 2.7.** 2.7 is historical. Nothing new goes there. The generator's input
      location for the 49 old chapters is a fact about history, not a rule for new chapters.
- [ ] **Proof before push.** The analysis image was built on compute from the changed Dockerfile
      (`FROM ghcr.io/appliedepi/aedockerpublic/epirhandbook-common:2.8`): BUILD_EXIT=0, LOAD CHECK
      OK for all 253 names. The chapter then rendered inside that image with `--network none`.
- [ ] **README.** Rewritten for 2.8. The old text described 2.7 and said all 51 images were
      private. Verified by anonymous manifest GETs: the nine 2.8 images return 200, the 2.7
      per-chapter images return 403.
- [ ] **What CI will do on push.** `changed_images.py` sees `groups/analysis/` and `monolith/`
      changed, so it rebuilds `epirhandbook-analysis:2.8` and `epirhandbook-monolith:2.8` and
      republishes both tags in place. `common` and `rbase` are untouched. The handbook push must
      wait for that publish, or staging goes red with a missing-package error.
- [ ] **Round two (PR #1, branch gis-pins).** babeldown, babelquarto and tinkr pins removed; brio,
      fs and xml2 made explicit in common (the render scripts import them; brio had come in only
      through the removed pins, caught by the codex plan review, confirmed by `requireNamespace`
      inside the pin-free image); appliedepidata pinned to the sle_hf commit (appliedepidata PR #47),
      to move to the merge commit before this PR merges; gis listed under analysis renders.


---

## Phase 4 — productionize: supply-chain controls

> **Historical record, not current documentation.** §8.1 through §8.10 below
> describe the state of this project AS IT WAS at the time each subsection was
> written, during Phase 4. Later work — including §8.10's own `base_digest`
> removal and the sweep that followed it — has since changed some of what
> earlier subsections describe (an inline `[since removed ...]` note marks
> each specific passage this is known to affect). Do not read §8.1-8.10 as a
> description of today's behavior. For that, read `images.yaml`'s own field
> comments and the module-header docstrings in `.github/scripts/` (`plan.py`,
> `build_image.sh`, `changed_images.py`) — there is no repository README yet
> beyond a two-line stub.

Phase 4 adds `images.yaml`, manifest-driven CI (`.github/workflows/build.yml` +
`nightly.yml`), and a publish path to GHCR. Round 1 of adversarial review **blocked**
the first implementation on 4 blockers + 5 further findings. §8.1-8.7 records how
each was closed. Round 2 **blocked again**, on one genuine supply-chain risk (a
registry-write-capable token reaching arbitrary package-build code) plus parser and
documentation findings; §8.8 records how each of THOSE was closed. The vendored YAML
reader round 1 introduced (`minimal_yaml.py`) then drew two further rounds of
parser-only findings before the decision to vendor it at all was reversed: it is
deleted outright, replaced with hash-pinned PyYAML plus a strict schema validator;
§8.9 records that reversal and why. **Status: remediation complete, not yet
re-reviewed.** Nothing has been published; the first-ever publish has still never
been run.

### 8.1 Publishing only ever happens from `main`

Both `build.yml` and `nightly.yml` open with a `guard-main-ref` job: one step compares
`github.ref` to `refs/heads/main` and `exit 1`s with an `::error::` if they differ.
Every other job `needs:` it, directly or transitively (`plan`'s existing
`needs.plan.result == 'success'` check already turns a skipped `plan` into a skipped
build downstream).

This lives in the workflow itself, not only in `build.yml`'s `on: push: branches:
[main]` filter or a repo setting — both are config that could be edited or bypassed by
an admin. `build.yml` also gained `workflow_dispatch` (to carry the
`force_republish_frozen` override, §8.3); the guard is what keeps that safe — a
dispatch from a branch fails immediately, before checkout even runs.

### 8.2 `nightly.yml` no longer publishes anything

[Since removed: `nightly.yml` itself no longer exists in `.github/workflows/`
as of this writing — confirm with `ls .github/workflows/`. See the historical-
record banner at the top of §8.]

Restructured from "rebuild every live image and push" into drift detection: build
every live image, let each Dockerfile's own build-time invariants run, then stop.

- **No `packages: write` anywhere in the file.** Top-level `permissions: contents:
  read`; no job overrides it.
- **No `docker push`, no `docker/login-action` step, anywhere.** `build_image.sh`
  gained a `verify` mode (alongside `publish`) that builds and inspects but never
  pushes; `nightly.yml` calls it exclusively in `verify` mode.
- **What counts as drift:** does `docker build` still succeed, with every shortcut
  re-checked rather than assumed (a freshly-built base uses its own fresh local tag; a
  base NOT rebuilt this run has its recorded digest actively re-checked against the
  registry first — §8.6)? For `epirhandbook`, "the build succeeded" already means "all
  473 `renv.lock`-pinned packages resolved, installed, and load at their exact locked
  version" — that check is Phase 2's unconditional build-time RUN step in
  `epirhandbook/2.5/Dockerfile`, so nightly needs no separate step for it. `rbase`
  carries its own analogous invariants (R version + BLAS/LAPACK, Quarto's sha256).
  Deliberately NOT attempted: rendering real chapter content and diffing it against a
  live crawl of epirhandbook.com. That needs a different repo's content plus a live
  crawl of a third party's production site — Phase 2/3's one-time regression-bar
  infrastructure (`epirhandbook/2.5/verify/`), not something to run unattended every
  night, nor available in a CI runner without vendoring the crawl data this project
  deliberately keeps out of git. Full reasoning is in `nightly.yml`'s own header.
- **Structural difference from `build.yml`:** one job (`drift-check`), not one job per
  layer. Nightly builds sequentially on a single runner, so a freshly-built base is
  referenced by its plain local Docker tag directly — no registry round-trip, because
  nothing gets pushed. As a side effect this also removes the layer-count ceiling for
  nightly specifically (it walks `plan.json`'s layers with `jq`, however many exist);
  `build.yml` still has the static ceiling, now hard-failed in `plan.py` (§8.6).

### 8.3 `frozen: true` — a published version never moves by accident

Both `rbase` and `epirhandbook` are marked `frozen: true` in `images.yaml` (see the
field's own comment there). In `publish` mode only, `build_image.sh` checks — before
pushing any tag of a frozen image — whether that tag already exists in the registry
(`docker buildx imagetools inspect`). If it does, refuse: `exit 1` with an `::error::`
naming the image and tag, UNLESS the image's name is listed in
`FORCE_REPUBLISH_FROZEN`, sourced from `build.yml`'s `workflow_dispatch` input
`force_republish_frozen` — a human, dispatching by hand, saying "yes, really replace
this." Never set by automation; `nightly.yml` has no such input and cannot push at all
regardless.

Verified end to end against a real local registry on compute (`registry:2` at
`localhost:5000`) using the real `build_image.sh`, not a stand-in: a first publish of a
fresh tag succeeds; a second attempt at the same tag refuses (exit 1); a third attempt
with the override set succeeds (exit 0).

**Round 2 update (§8.8):** this same check now ALSO runs standalone, as its own
`build.yml` step, before `docker/login-action` and `docker build` — not only inline
inside `publish` mode as described above (which is unchanged and still true).

### 8.4 Supply-chain pins

- **Every third-party action pinned to a full commit SHA**, version in a trailing
  comment (fetched from the live GitHub API, not guessed):
  - `actions/checkout@11d5960a326750d5838078e36cf38b85af677262` — v4.4.0
  - `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065` — v5.6.0
  - `docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9` — v3.7.0
  - `nick-fields/retry@ce71cc2ab81d554ebbe88c79ab5975992d79ba08` — v3.0.2

  Each is pinned to whatever major-version tag was already in use (v4/v5/v3/v3) — a
  supply-chain fix (mutable tag -> immutable SHA), not a version bump.
- **`pip install pyyaml` removed entirely, not hash-pinned — REVERSED, see §8.9.**
  `images.yaml`'s shape is small and fully owned by this project (see its own header
  for the field list), so `.github/scripts/minimal_yaml.py` was a vendored reader
  supporting exactly that shape (a block sequence of flat mappings; schema-validated
  keys; strictly-cased quoted/bare/null/bool scalars; one level of inline
  flow-sequence respecting quotes; comments) and raising `ValueError` on anything
  outside it, rather than silently mis-parsing. Cross-checked byte-for-byte against
  `yaml.safe_load()` on the real file; unit-tested in `test_plan.py`'s
  `TestMinimalYaml` (including a real bug the tests caught during development: an
  early version accepted indentation *at least* 4 spaces as a continuation line,
  which would have silently flattened a genuinely nested value instead of rejecting
  it — tightened to *exactly* 4). **This "raises on anything outside it" claim was
  NOT actually true when first written** — round 2 review found four confirmed cases
  the parser silently misread instead of rejecting (worst: `live: False`, capital F,
  parsed as the truthy *string* `"False"`, silently *including* an image the catalog
  said to exclude); round 3 and round 4 each found further such cases afterward (see
  §8.9). **The decision this bullet describes is reversed as of §8.9:**
  `minimal_yaml.py` is deleted, not patched a fifth time. PyYAML is now the real
  parser, hash-pinned in `.github/scripts/requirements.txt`, with a strict
  `validate_catalog()` allowlist schema on top — see §8.9 for the full reasoning and
  what replaced every test this bullet used to point to.
- **`packages: write` scoped to only the jobs that push** (`build-layer-0..3` in
  `build.yml`). Every other job — `guard-main-ref`, `plan`, and all of `nightly.yml` —
  gets the workflow-level `contents: read` default and nothing more.
- **The package-build step never receives a registry-write-capable credential.**
  `GITHUB_PAT` (fed to `docker build` as a BuildKit secret, used only to raise pak's
  GitHub API rate limit while resolving epirhandbook's 7 GitHub-pinned packages) is
  sourced from `GH_READONLY_PAT` — a dedicated repository secret, a fine-grained PAT
  scoped to **public read only** (no `packages: write`, no repo write of any kind) —
  in both `build.yml` and `nightly.yml`, never from `secrets.GITHUB_TOKEN`. This was
  round 2's blocker; §8.8 has the full story and the compute verification.

  **To create/rotate `GH_READONLY_PAT`:** GitHub -> Settings (personal) -> Developer
  settings -> Fine-grained personal access tokens -> Generate new token. Resource
  owner: the token owner (does not need to be an org member beyond what's needed to
  read public content). Repository access: Public Repositories (read-only) is
  sufficient — this token exists only to raise the ANONYMOUS GitHub API rate limit
  for 7 already-public package repos, not to access anything private. No permissions
  need `write`. Save it as repo Settings -> Secrets and variables -> Actions ->
  New repository secret, named exactly `GH_READONLY_PAT`. If it is left unconfigured,
  the build proceeds with NO token at all (never a silent fallback to
  `secrets.GITHUB_TOKEN`) — the only consequence is that those 7 lookups fall back to
  the anonymous GitHub API rate limit, shared across every job on the same
  GitHub-hosted runner IP at that moment.

### 8.5 Publish gate

- **`main`-only** — §8.1.
- **`.github/CODEOWNERS`** covers `.github/**` and `images.yaml`, owner `@raubreywhite`
  (confirmed via the GitHub API against the real `appliedepi/aedockerpublic` commit
  history — not guessed). Only takes effect once "Require review from Code Owners" is
  turned on for a rule covering `main`; see the file's own header for exactly where.
- **`publish` GitHub Environment** on every job in `build.yml` that pushes
  (`build-layer-0..3`). **To require a reviewer:** repo Settings -> Environments ->
  New environment -> name it exactly `publish` -> Environment protection rules ->
  Required reviewers -> add yourself (or a team) -> Save. Until that's done,
  `environment: publish` is inert (GitHub auto-creates an environment with no
  protection rules the first time a run references a name that doesn't exist yet) — it
  is NOT assumed to be on.
- **Deliberately NOT done: forcing pull requests, or removing admin bypass.** Direct
  pushes to `main` are an informed choice (see §3's note on the earlier
  branch-protection bypass). **Residual risk:** a workflow-file change can alter what
  gets published in the SAME push that introduces it — nothing here reviews a workflow
  diff before it takes effect on its own next run. The `publish` environment's
  required-reviewer gate, once turned on, is the mitigation: it interposes a review
  step between "code is pushed" and "packages: write actually executes," regardless of
  what the workflow file itself now says. It is off by default, and this project has
  not turned it on.

### 8.6 Planner hardening

- **An unknown `base:` name is now a hard error.** Before: a typo (e.g. `base:
  rbse:4.3.2`) looked, to the topological sort, IDENTICAL to "this image has no base"
  — both are "not in `remaining`". The image would silently build as if base-less, and
  its cascade edge (rebuild me when my base rebuilds) would silently never fire again.
  Now `topological_order()` validates every `base:` against the full catalog before
  sorting, and raises `ValueError` naming the offending image, the bad name, and the
  known-good names. Test: `test_unknown_base_name_is_a_hard_error` in
  `.github/scripts/test_plan.py` (shown red, then green, during development).
- **A catalog deeper than 4 layers is now a hard error, not a silent partial publish.**
  `plan.py`'s `MAX_SUPPORTED_LAYERS = 4` matches `build.yml`'s wired-up
  `build-layer-0..3` jobs; `topological_order()` raises `ValueError` if the real
  catalog ever needs a 5th. Invisible today (2 images, 2 layers); a real risk once
  Phase 5a adds ~50 chapter images. Test:
  `test_catalog_deeper_than_max_layers_is_a_hard_error` (a synthetic 5-image chain).
- [Since removed: this whole guard — the `base_digest` field and the comparison
  described below — no longer exists; see §8.10.]
- **A stale `base_digest` is now caught before it's used.** `build_image.sh`'s
  steady-state branch (base NOT rebuilt this run) queries the base's floating tag live
  and compares it to the recorded `base_digest` BEFORE building against it — if they
  disagree, `exit 1` naming both digests and which `images.yaml` field to update.
  Verified against a real local registry (`registry:2` on compute, `localhost:5000`):
  the agreeing case exits 0 and proceeds; the disagreeing case exits 1 with that exact
  message.

### 8.7 Concurrency and SSH hardening

- **The concurrency group is ref-independent** (`aedockerpublic-ghcr-builds`, no
  `-${{ github.ref }}` suffix) in both workflows, so a dispatch from any ref serializes
  against every other run capable of touching these images, not just runs sharing its
  own ref.
- **`sshd_hardening.conf` gained** `AllowTcpForwarding no`, `X11Forwarding no`,
  `PermitTunnel no`, `GatewayPorts no`, `AllowAgentForwarding no`. The Dockerfile's
  existing build-time `sshd -T` assertion was extended to check all five in the
  EFFECTIVE config, not just the source file. Confirmed on a real rebuild of `rbase` on
  compute: `sshd -T` reports all 9 hardening settings (the original 4 plus these 5)
  correctly in effect.

### 8.8 Round 2 remediation — token privilege and parser strictness

Round 2 of adversarial review blocked on one genuine supply-chain risk plus parser
and documentation findings.

**Blocker: the build received a registry-write-capable token.** `build.yml`'s
`build-layer-N` jobs hold `packages: write`, and used to set `GITHUB_PAT:
secrets.GITHUB_TOKEN` on the "Build and push" step — feeding a token that CAN push to
`ghcr.io/appliedepi/aedockerpublic/` into `docker build`, where `epirhandbook/2.5`'s
`Rscript pak_install.R` downloads and compiles 473 packages, several with their own
post-install scripts. Arbitrary package-build code should never hold a credential
able to publish. Fixed:
- A new repository secret, `GH_READONLY_PAT` — a fine-grained PAT scoped to public
  read only (no `packages: write`, no repo write) — is what `GITHUB_PAT` is now
  sourced from, in both `build.yml`'s `build-layer-N` jobs AND `nightly.yml`'s
  `drift-check` job (nightly's own `GITHUB_TOKEN` was already `contents: read`-only
  in practice, since nightly never elevates permissions — but it is switched too, so
  both workflows feed the exact same package-build code the exact same KIND of
  credential for the exact same purpose, rather than two different tokens depending
  on which workflow happens to run it). `secrets.GITHUB_TOKEN` is untouched for its
  own legitimate jobs: `docker/login-action` and the eventual `docker push`.
- If `GH_READONLY_PAT` is not configured, the relevant env line
  (`GITHUB_PAT: ${{ secrets.GH_READONLY_PAT }}`) simply evaluates to an empty
  string — GitHub Actions does not error on an undefined secret reference, and
  there is no `||`-fallback to `secrets.GITHUB_TOKEN` anywhere, so there is no code
  path by which the write-capable token could still reach the build.
  `build_image.sh` treats an empty/unset `GITHUB_PAT` as "build with no token at
  all": it still passes `--secret id=github_pat,env=GITHUB_PAT` (an empty secret is
  valid to BuildKit), and pak's `github::` resolution for the 7 GitHub-pinned
  packages then relies on the ANONYMOUS GitHub API rate limit instead of an
  authenticated one. Documented in both workflow headers and in §8.4 above.
- Verified on compute: `build_image.sh verify` (no push/login needed) built
  `epirhandbook` FROM the existing local `rbase:4.3.2`, with `GITHUB_PAT` explicitly
  UNSET and Docker's layer cache forced off (`--no-cache`, since a secret's VALUE is
  deliberately excluded from BuildKit's cache key, so a plain re-run would silently
  reuse the earlier cached result and prove nothing) — all 473 packages still
  installed and the version/load check still passed, with `Config.Env` and
  `docker history --no-trunc` both showing zero occurrences of any token. See the
  round 2 remediation session's returned evidence for the exact build log tail and
  grep counts.
- **The frozen-tag check now runs BEFORE `docker build` and BEFORE
  `docker/login-action`,** not just before `docker push`. `build_image.sh` gained a
  `check-frozen` mode (repo/name/tags/frozen only — no base info, no docker build) that
  `build.yml` now runs as its own step, ahead of the login step, in every
  `build-layer-N` job. A doomed republish attempt (frozen, tag already published, no
  `force_republish_frozen` override) is now refused before the job ever exchanges the
  registry-push credential via `docker/login-action` and before it spends the
  ~45-minute compile, not merely before the final `docker push`. The identical check
  (same `check_frozen_or_die` shell function) still ALSO runs inline inside `publish`
  mode itself, before base resolution — kept there too, not removed, so
  `build_image.sh` stays self-contained: a human invoking it directly in `publish`
  mode (as this project's local-registry rehearsal in §8.3 does) still gets the
  refusal without depending on `build.yml`'s own step ordering.

**Parser findings: `minimal_yaml.py` silently read valid YAML wrong.** §8.4's
"raises on anything outside it" claim was not actually true when first written.
Four confirmed cases, all now hard errors instead of silent mis-parses:
1. `live: False` (capital F) used to parse as the STRING `"False"` — truthy in
   Python, so an image the catalog said to exclude was silently INCLUDED instead
   (the worst kind of failure: valid YAML, inverted meaning, no error anywhere).
   Now only lowercase `true`/`false`/`null` are recognized as typed scalars; any
   other casing is a hard `ValueError` naming what was found.
2. `tags: ["a,b"]` used to split on the comma INSIDE the quotes; `tags: ["1",]`
   used to silently yield `["1", null]`. The flow-sequence parser now scans
   char-by-char respecting quotes (a comma inside quotes never splits) and treats
   any empty item (trailing/doubled comma) as a hard error, never a null.
3. Quote/comment toggling flipped on every quote character with no escape
   semantics, so a backslash inside a quoted value (e.g. an escaped quote) was
   silently mishandled rather than rejected. Any backslash encountered while
   scanning inside quotes — in comment-stripping, key/value-splitting, scalar
   parsing, or flow-sequence parsing — is now a hard error.
4. An unknown per-image key (e.g. a typo like `froze: true`) used to be accepted
   silently, leaving the correctly-spelled `frozen` key simply absent — which
   `plan.py` then quietly defaults to `False`, so the typo took effect with no
   error anywhere. `minimal_yaml.py` now schema-validates every image: an unknown
   key is a hard error (allowed keys: `name`, `dir`, `tags`, `base`,
   `base_digest`, `live`, `frozen`), and `name`/`dir`/`tags`/`base`/`base_digest`
   must all be present (`live`/`frozen` stay optional, matching `plan.py`'s own
   `.get(key, default)` fallback).

All four are covered by new tests in `test_plan.py`'s `TestMinimalYamlRound2Hardening`
(7 tests: both cases 1 and 2 get a positive/negative pair). All 7 were shown RED
against the pre-fix parser (each failing for exactly the stated reason — e.g. "ValueError
not raised" for the silent-acceptance cases, a wrong list value for the comma-splitting
case) before the fix, then GREEN after. `minimal_yaml.py` still parses the real
`images.yaml` byte-for-byte identically to `yaml.safe_load()`.

**Documentation overclaims, both corrected:**
- §8.4's `minimal_yaml.py` bullet (above) now says plainly that the "raises on
  anything outside it" claim was false when written, and points here.
- `images.yaml`'s `frozen:` field comment said a frozen image "is published ONCE,
  deliberately, by a human triggering build.yml" — but `build.yml` also publishes on
  an ordinary push to `main`, not only on a human-dispatched run. Corrected to say a
  frozen image is published exactly once, by WHICHEVER run of `build.yml` first
  reaches that tag (push or dispatch) — and that what IS a deliberate, one-time human
  action is specifically the `force_republish_frozen` override that would replace an
  already-published frozen tag.

### 8.9 Vendored-parser reversal — hash-pinned PyYAML replaces `minimal_yaml.py`

`minimal_yaml.py` traces to round 1: closing an unpinned `pip install pyyaml`
finding by vendoring a narrow reader instead of depending on a network-fetched
package. That reader then drew three further rounds of adversarial review, each
finding a fresh case where it silently assigned a DIFFERENT meaning than real YAML
would — never actually rejecting everything outside its supported subset, despite
its own docstring's claim:

- **Round 2** (§8.8): four confirmed cases — a capitalized `False` parsed as the
  truthy string `"False"`; a comma inside quotes (`["a,b"]`) split into two tags; a
  backslash inside a quoted value silently mis-toggled the quote state instead of
  raising; an unknown per-image key (`froze` for `frozen`) was silently accepted.
- **Round 3**: YAML's OTHER boolean aliases — `yes`/`no`/`on`/`off`, any casing —
  were not rejected either; an unquoted `live: no` parsed as the truthy string
  `"no"`, same failure class as round 2's `False`, one spelling further out.
- **Round 4**: a `#` abutting a value with no preceding space was truncated as a
  comment instead of kept as part of the scalar (real YAML keeps it); a bare
  numeric scalar (`tags: [2.5]`) was kept as the string `"2.5"` instead of raising
  on the type disagreement with real YAML's float; a duplicate key in one image
  silently kept the last value instead of raising.

Four rounds of adversarial review blocking on the same "how do we read
images.yaml" decision is a pattern, not a run of bad luck. The vendored reader's
contract — "the same meaning as real YAML, or raise" — is UNBOUNDED. YAML's
implicit scalar grammar (dates, times, hex, octal, sexagesimal, several spellings
of boolean, several of null, ...) is larger than any hand-rolled rejection list, so
every round found a construct the list did not yet cover. Patching the list a
fifth time would not close that gap; it would only move where the next gap is.

**The decision is reversed.** `minimal_yaml.py` is deleted, not patched again.
`plan.py` now uses real PyYAML (`yaml.safe_load`) to parse `images.yaml`, and a
strict ALLOWLIST schema, `validate_catalog()`, to check the result. Every field
has exactly one declared type; anything else is a hard `ValueError` naming the
file, the image, the field, and what was expected:

| Field | Rule |
|---|---|
| top level | a mapping with exactly one key, `images`, mapping to a non-empty list |
| `name` | non-empty `str` matching `^[a-z0-9][a-z0-9._-]*$` (image-name safe) |
| `dir` | non-empty `str`; relative path (no leading `/`, no `..` segment) |
| `tags` | non-empty `list`; every element a non-empty `str` |
| `base` | `null`, or a non-empty `str` |
| `base_digest` | `null`, or a `str` matching `^sha256:[0-9a-f]{64}$` exactly |
| `live` / `frozen` (optional) | a real `bool` (`isinstance(x, bool)`) — a quoted `"true"` is a `str` and is rejected |
| any key not in `{name, dir, tags, base, base_digest, live, frozen}` | hard error |

[Since removed: `base_digest` and `frozen` are both gone from
`plan.py`'s live `ALLOWED_IMAGE_KEYS` — see §8.10 for the `base_digest`
removal; `frozen`'s removal is not separately narrated in this document.]

This is bounded where the vendored reader was not: PyYAML is a complete, real
YAML implementation, so it already resolves every implicit scalar correctly —
there is no rejection list to keep extending. The schema only has to state, once
per field, the ONE type that field is allowed to be; whatever a future YAML
construct resolves to, it either matches that one type or it is rejected, with no
gap to rediscover later. This is exactly how `tags: [2024-01-01]` is caught:
`validate_catalog()` does not need to know PyYAML turns an unquoted date into a
`datetime.date` — it only needs to know a tag must be `str`, and a `datetime.date`
is not one. The same reasoning catches `tags: [2.5]` (a `float`), regardless of
what other numeric or timestamp forms YAML might resolve in the future.

**PyYAML is hash-pinned, not left unpinned** — round 1's ORIGINAL finding, closed
the way it actually asked for, instead of avoided by vendoring.
`.github/scripts/requirements.txt` pins `PyYAML==6.0.3` (PyPI's current stable
release) with `--hash=sha256:...` lines fetched from PyPI's JSON API: the sdist
plus manylinux x86_64 wheels for CPython 3.9 through 3.14, covering GitHub's
`ubuntu-latest` runner regardless of which "3.x" `actions/setup-python` resolves
to at run time. Both `build.yml` and `nightly.yml` install it with
`python -m pip install --require-hashes -r .github/scripts/requirements.txt`,
right after `actions/setup-python` and before the planner's own unit tests run —
a downloaded artifact that does not match one of the recorded hashes is refused,
never installed. Verified on bench: installing into an isolated `--target`
directory with the real hash succeeds; the identical install with one hash
character zeroed out is refused (`THESE PACKAGES DO NOT MATCH THE HASHES`).

**Tests.** `test_plan.py`'s `TestMinimalYaml`, `TestMinimalYamlRound2Hardening`,
`TestMinimalYamlRound3BooleanAliases`, and `TestMinimalYamlRound4` classes (all
specific to the deleted parser) are replaced by one `TestValidateCatalog` class —
16 tests, each driving a real YAML string through `yaml.safe_load()` and then
`plan.validate_catalog()`, covering every row of the table above. Every other
test (the cascade/planner logic in `RequiredCases` and `ExtraCases`, and the
`TestAgainstRealCatalog` canary) is unchanged, since none of them depend on how
the catalog gets parsed. Full suite: 32 tests, all green. Two deliberate
red-then-green demonstrations during development: disabling the `live`/`frozen`
real-bool check failed exactly the two tests that assert it, both `ValueError not
raised`; separately, weakening `base_digest`'s regex to accept anything failed
exactly the one test asserting a malformed digest is rejected, also `ValueError
not raised`. Both breaks were restored (confirmed byte-identical to the working
version) and the full suite is green again.

**Status: implemented, not yet re-reviewed** — same as round 2 before it. This
closes a review finding but has not itself been through adversarial review.
Nothing has been published; the first-ever publish has still never been run.

### 8.10 `base_digest` retired — the optional cross-check is now dead weight

The OCI-revision change model (§8.2/§8.6) already made `build_image.sh` resolve
every base image's digest LIVE from the registry on every build — from the
image it just pushed if the base was rebuilt this same run, else from the
base's published tag. That live resolution is unconditional; `base_digest` had
already been demoted (§8.6, §8.9's field table) to an OPTIONAL cross-check that
only fired in the one branch where the base was NOT rebuilt this run, and even
there it only compared against the digest the live resolution had already
fetched. A field that can never change the outcome of a build, and that a human
would otherwise have to hand-update after every base rebuild (the old
Digest-pinning procedure below), is not a cross-check worth keeping — it is
maintenance burden with no corresponding safety property. It is removed
outright, the same treatment `frozen` got when the OCI-revision model made its
guard redundant: gone from the live catalogs and code, but the field's own
historical description in §8.6/§8.8/§8.9 above is left exactly as written,
because those sections record what was true DURING Phase 4, not what is true
now.

Removed:
- **`images.yaml`** (root): the `base_digest` field's entry in the `Fields:`
  doc block, the ~45-line "Digest-pinning procedure" comment block describing
  the old manual pin-recording workflow, and the one `base_digest: null` row
  for `rbase`. The file's own "read by" comment no longer claims anyone reads
  it "to know the current base_digest pin" — nobody has, since the field did
  nothing.
- **`epirhandbook/2.7/images.yaml`**: `base_digest: null` dropped from all 50
  rows (this catalog IS read by CI, so it stays schema-valid throughout).
- **`.github/scripts/plan.py`**: `base_digest` out of `REQUIRED_IMAGE_KEYS`
  and `ALLOWED_IMAGE_KEYS`; the two validation checks specific to it (digest
  format, and "digest without a base is meaningless"); `DIGEST_RE`, which had
  no other consumer.
- **`.github/scripts/build_image.sh`**: the `BASE_DIGEST` positional argument
  and the steady-state comparison against it, and every stale comment
  pointing at the now-deleted images.yaml procedure. Every positional after
  the removed one is renumbered (`BASE_FRESH` was `$8`, is now `$7`;
  `GIT_COMMIT` was `$9`, is now `$8`; `CONTEXT` was `${10}`, is now `${9}`) —
  `build.yml`'s four `build_image.sh publish` call sites are updated to match
  exactly.
- **`.github/workflows/build.yml`**: `matrix.image.base_digest` dropped from
  all four build-layer invocations.
- **`.github/scripts/test_plan.py`**: `base_digest` stripped from every
  fixture and inline YAML string; `test_short_base_digest_is_rejected`,
  `test_real_64_hex_digest_is_accepted`, `test_null_base_digest_is_accepted`,
  and `test_base_digest_without_a_base_is_rejected` deleted outright — their
  entire subject was validating a field that no longer exists.
- **`epirhandbook/2.7/generate.py`**: the line writing `base_digest: null`
  into the generated catalog (this mattered even though the generator is
  slated for archival: `plan.py`'s allowlist would hard-reject a catalog it
  generated with the old field still in it).
- **`epirhandbook/2.7/common/Dockerfile`**: the `BASE_IMAGE` ARG comment's
  pointer at the now-deleted procedure, reworded to describe what actually
  resolves it (`build_image.sh`'s live base-resolution block) instead.

**Deliberately NOT touched**: `epirhandbook/2.5/Dockerfile`,
`epirhandbook/2.6/README.md`, `epirhandbook/2.6/generate.py`, and
`epirhandbook/2.6/images.yaml` (50 rows, `base_digest: null` throughout) all
still mention the retired field. That tree is frozen provenance, never loaded
by any CI path — `build.yml` only ever passes `--images-yaml images.yaml
--images-yaml epirhandbook/2.7/images.yaml` to `plan.py` — so leaving it alone
is correct, not an oversight.

**Causally-red probe**: reintroducing a single `base_digest: null` line into
`epirhandbook/2.7/images.yaml` and re-running `plan.py` against both live
catalogs fails immediately, naming `base_digest` as an unknown key against
`ALLOWED_IMAGE_KEYS` — proof the allowlist actually rejects the removed field
rather than merely no longer requiring it.

**Status: implemented, not yet re-reviewed** — same as every entry in this
section before it.

---

---

## Phase roadmap and status

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

---

## The problem

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
