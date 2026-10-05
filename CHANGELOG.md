# CHANGELOG: aedockerpublic / epiRhandbook image lines

This file records what each image line changed, and why. The newest entry comes first.

This file was split out of `PROJECT.md` on 2026-09-17, and `PROJECT.md` was then deleted. Its standing material moved to `README.md`, and its history came here. Each entry describes the project as it was on the day the entry was written. Later work changed some of it. Read this file as a record, not as current documentation.

---

## 2.9 addendum (2026-10-05): plain prose, and stale comments corrected

- [ ] **Comments, docstrings and Markdown are rewritten in plain prose.** No code changed, except two error messages: the unknown-base error in `plan.py` says "the catalog", not "images.yaml", and the missing-rsync error in `build_all_chapters.sh` gives the right reason. The Markdown files have no hard line wraps.
- [ ] **Stale comments are corrected.** The group and monolith Dockerfile headers give the current package counts (254 and 321). The `rbase/4.6.0` SSH comments describe Ubuntu 26.04, not jammy. `checks.yml`, `build.yml`, `plan.py`, `build_all_chapters.sh` and `CODEOWNERS` no longer describe steps, fields or references that do not exist.
- [ ] **README.md lost its 2.5-era maintenance notes.** They described the renv-locked build on `rbase:4.3.2`. They are kept at the end of this file. The visibility section lists the tags the registry held on 2026-10-05.

---

## 2.9 addendum (2026-10-05): fixes from issue #7

- [ ] **The common package count is 58 everywhere.** `README.md` and the install comment in `common/Dockerfile` said 59. `common/packages_cran.txt` holds 58 names.
- [ ] **`build_all_chapters.sh` removes its workspace after a successful build.** It also removes its manifest temp file. A failed build keeps the workspace for inspection. A failed removal logs a warning and does not fail the build, because the output is already complete. The render containers write root-owned files, so a container in the common image deletes them.
- [ ] **`build_all_chapters.sh` checks each chapter image for `warnings_to_log.R` before the image's first render.** An image built before the profile was added does not hold it, and its own `build_one_chapter.sh` does not check. The render then logged no warnings, and the handbook's check 17 failed without naming the cause. Now the build stops and names the chapter, the image and the missing file. A docker failure, such as an image that cannot be pulled, stops the build with its own message.
- [ ] **The `changed_images.py` docstring no longer says it is the only CI code that reads the registry.** `build_image.sh` reads it too, to resolve the digest of an image's base.
- [ ] **Verified with a stub `docker` on `PATH`**, because bench has no docker. On `common/test_fixture`, a green run exited 0 and left no new directory under `/tmp`. A run with a chapter on an image that lacks the profile exited 1 with the new error, and kept its workspace.

---

## 2.9 addendum (2026-10-01): the analysis image carries ncmeta, so time_series can read NetCDF without GDAL

- [ ] **`groups/analysis/packages_cran_time_series.txt` lists `ncmeta`.** `generate_groups.py` added it to `groups/analysis/packages_cran.txt` and `monolith/packages_cran.txt`. pak installs ncmeta 0.4.0 and its import RNetCDF 2.11-1 from the snapshot. Before, no published 2.9 image held either package.
- [ ] **Why.** The `time_series` chapter reads the 10 `germany_weather` NetCDF files with `stars::read_stars`. That reader goes through GDAL, which raises "GDAL Message 1: 1-pixel width/height files not supported" twice per file. `stars::read_ncdf` does not use GDAL, but it needs ncmeta. This entry changes the image only. The chapter still calls `read_stars`.
- [ ] **Verified on the compute host.** `epirhandbook-analysis:2.9-ncmeta`, built in verify mode FROM the published `epirhandbook-common:2.9`, printed `LOAD CHECK OK: all 254 target packages load` and passed the smoke render. With no network, `read_ncdf` read each of the 10 files with 0 warnings. `read_stars` raised 20 warnings on the same files. In the published `epirhandbook-analysis:2.9`, `read_ncdf` stopped on each file with "package ncmeta required".
- [ ] **What CI will do on push.** The changed lists sit under the `dir` of `epirhandbook-analysis` and of `epirhandbook-monolith`, so those two images rebuild. Nothing else rebuilds.

---

## 2.9 addendum (2026-10-01): each image renders a smoke document before it is pushed

- [ ] **`build_image.sh` renders `common/smoke.qmd` in each image it builds.** The render runs after `docker build` in both modes, before any push and before verify mode exits. A failed render stops the script with exit 1, so publish mode pushes nothing.
- [ ] **The render uses the image's own `build_one_chapter.sh`.** The container has `--network none` and `R_PROFILE_USER=/usr/local/lib/ehb/warnings_to_log.R`, the profile that `build_all_chapters.sh` sets. It copies the document to a new directory and runs as the image's default user. The script also fails when no `smoke.html` exists.
- [ ] **`smoke.qmd` holds an R chunk that computes and checks a value, a ggplot2 plot and a `knitr::kable` table.** `epirhandbook-common` installs it at `/usr/local/lib/ehb/smoke.qmd`, so the six group images and the monolith carry it too.
- [ ] **An image without `/usr/local/bin/build_one_chapter.sh` gets no render, and the log names it.** Today that is `rbase` alone. The script runs `test -x` in the image. Exit 1 means skip. Any other exit is a docker failure, and it stops the script.
- [ ] **Why.** The build checked that each package loads. Nothing checked that the image renders a page before the push, so a broken Quarto, knitr or R profile could reach the registry.
- [ ] **What it does not show.** A pass does not show that an image holds every package its chapters need, or that the R profile logs warnings. `build_all_chapters.sh` and `common/test_fixture/` check those.
- [ ] **Verified on the compute host.** `epirhandbook-common:2.9-p5`, built in verify mode, rendered the document and exited 0. `rbase`, built in verify mode with the tag `4.6.0-p5-2026-07-01`, logged the skip and exited 0. A `smoke.qmd` that calls `stop()` made the build exit 1, and so did a `build_one_chapter.sh` that exits 1. In publish mode, a docker shim recorded each push: the `stop()` build recorded 0 pushes, and the real document recorded 1. The previous `build_image.sh` built the `stop()` image and exited 0.
- [ ] **What CI will do on push.** `.github/scripts` is a machinery directory, so `changed_images.py` reports all nine catalogue images as changed and the run plans all nine. `epirhandbook-common` and the seven images built FROM it each run the smoke render, which took 10 to 13 seconds on the compute host. `rbase` logs the skip.

---

## 2.9 addendum (2026-10-01): an image built FROM an old base is rebuilt

- [ ] **`build_image.sh` stamps each image that has a base with `org.opencontainers.image.base.digest`.** The value is the digest of the base image that the build is FROM. In verify mode, a base built earlier in the same run has no registry digest, so the label holds its local image id.
- [ ] **`changed_images.py` now reports an image with a base as changed in three more cases:**
  - the image has no such label;
  - the published digest of its base cannot be read;
  - the label differs from the digest that the base's tag points to now.
- [ ] **Why.** README said that resume after a partial publish was automatic, and it was not. Say `epirhandbook-common` published at commit S and a group image failed both attempts. A rerun found common unchanged, because its revision label was S. It found the group unchanged too, because a change under common's `dir` is not in the group's own diff. The group stayed on the old common, and nothing failed. A base rebuilt from the same commit had the same defect: its digest changes, and no commit comparison sees that.
- [ ] **An image with `live: false` skips the check.** A moved base is the automatic rebuild that `live: false` opts out of. All nine catalogue images are live.
- [ ] **The three registry reads are parameters of `image_is_changed`.** `revision_of`, `labels_of` and `digest_of` default to the real reads. The tests pass dicts, so no test in `test_changed_images.py` reads the registry or runs docker. Before, the never-published test called the real registry. The command line reads the labels of each image once, for both the revision and the base digest label. The digest read uses `--format "{{json .Manifest}}"`, because buildx 0.11.2 ignores `{{.Manifest.Digest}}` and prints its default text.
- [ ] **Verified on the compute host.** `epirhandbook-common:2.9-p4`, built in verify mode, carries `sha256:38e4d976de6e20fc23e55184db7fe4d774747c226e63698400f2e6634c65621b` in the label. That is the registry digest of `rbase:4.6.0-2026-07-01`. The same build by the previous `build_image.sh` has no such label. Against the previous `changed_images.py`, 5 of the 8 new tests fail on their assertions. The other 3 pin behaviour that did not change. At `--sha 46c3310`, the published revision of the 2.9 images, the new script reports the 8 images with a base as changed. The previous script reports all 9 unchanged.
- [ ] **What CI will do on push.** `.github/scripts` is a machinery directory, so `changed_images.py` reports all nine catalogue images as changed and the run plans all nine. No published image carries the new label yet. So this first run would mark the 8 images with a base as changed even without the machinery change. `rbase` has no base.

---

## 2.9 addendum (2026-10-01): chapters render offline, every chunk warning reaches the log, and a dead fragment fails the build

- [ ] **Every chapter container of `build_all_chapters.sh` now runs with `--network none`.** Before, a chapter that called `pacman::p_load()` on a package missing from its image installed it during the render and exited 0. The image defect stayed hidden. That render now fails.
- [ ] **A new R profile, `common/warnings_to_log.R`, logs every chunk warning.** `epirhandbook-common` installs it at `/usr/local/lib/ehb/warnings_to_log.R`, and every chapter container gets `R_PROFILE_USER` set to that path. Each warning writes `EHB-WARNING<TAB><input file><TAB><chunk label><TAB><message>` to stderr, for `warning` set to true, false or NA, in the chunk or for the whole document. Each error that an `error: true` chunk captures writes an `EHB-ERROR` line. `message()` output writes nothing.
- [ ] **Why a profile.** A `warning: false` chunk dropped its warnings, and R's own report batches more than 10 into "There were 12 warnings". The log could not say which chunk raised what. The profile wraps knitr's `evaluate` hook at the start of each chunk, because Quarto sets its own knitr hooks after knitr loads. It passes `keep_warning = NA` where the chunk asked for FALSE. evaluate() captures nothing for both values, so the page does not change.
- [ ] **The profile reads a `.Rprofile` in the working directory.** `R_PROFILE_USER` stops R from reading it.
- [ ] **`build_one_chapter.sh` fails when `R_PROFILE_USER` names a missing file.** R ignores a missing profile and says nothing. A wrong path would then turn the log off with no error.
- [ ] **A dead same-page fragment now fails the build, and names each one as `<page>#<fragment>`.** A dead-fragment count that fails also fails the build. Before, the build printed the count, and printed `?` when the count failed. The 2.7 whole-book render held 106 dead fragments, so a handbook that still holds them fails until they are fixed.
- [ ] **`common/test_fixture/` is a two-chapter handbook for `build_all_chapters.sh`, with one variant per behaviour.** Its README says how to select a variant.
- [ ] **Verified on the compute host.** `epirhandbook-common:2.9-p3` was built in verify mode, and the real script rendered each fixture variant with it. The log held 1 `EHB-WARNING` line per render for `warning: false` and for `warning = NA`. It held 3 for `warning: true`, 12 for the document-level `warning: false`, and 0 for messages only. The old script with the published image logged 0 for each, and exited 0 on a missing package and on a dead fragment. The new script exits 1 on both. All 16 pages of the 8 variants that render are byte-identical to a render with `R_PROFILE_USER` unset.
- [ ] **What CI will do on push.** The image inputs that changed are all under `epirhandbook/2.9/common/`, so `epirhandbook-common` changes and every image built on it rebuilds. The two Markdown files rebuild nothing.

---

## 2.9 addendum (2026-10-01): i2extras is the seventh GitHub pin, and the build checks every pin's commit

- [ ] **`packages_github.json` pins `i2extras` at `reconverse/i2extras@10fea678`.** The dated PPM snapshot does not carry it, so it cannot go in a `packages_cran.txt`. pak resolves its dependencies `incidence2` and `ciTools` from the snapshot.
- [ ] **The build-time check of `epirhandbook-common` now reads the pin names from `packages_github.json`.** Before, it named `appliedepidata` alone, and no package list of any image names the other 5 pins. So no build-time check loaded them. A new pin is now checked with no edit to the Dockerfile.
- [ ] **A pin that loads at the wrong commit now fails the build.** The check compares the installed `RemoteSha` of each pin with the `RemoteSha` in `packages_github.json`. Before, a pin at any commit passed.
- [ ] **Verified on the compute host in verify mode.** `epirhandbook-common` printed `PIN CHECK OK: all 7 GitHub pins load at their pinned RemoteSha`. `epirhandbook-data-viz`, built FROM that image, loads `i2extras` at `10fea678` with no network. A wrong expected SHA failed the build with `PIN CHECK FAILED`. An install without `i2extras` failed it with `LOAD CHECK FAILED (1): i2extras`, and the old check passed that same install.
- [ ] **What CI will do on push.** `packages_github.json` is a shared context input of `epirhandbook/2.9`, so all eight 2.9 images rebuild: `epirhandbook-common`, the six group images and the monolith.

---

## 2.9 addendum (2026-09-24): an unquoted language code `no` stays a code

- [ ] **`build_all_chapters.sh` read `languages.yml` with `yaml.safe_load`.** That reads an unquoted `no` as False, so a Norwegian `code: no` stopped the build with "every languages[] entry needs a 'code'". `read_languages` now uses `yaml.BaseLoader`, which keeps every scalar a string. On the handbook's current `languages.yml` it prints the same two lines as before.
- [ ] **`inject_language_links.R` read the same file with plain `yaml.load_file`.** `code: no` became the text "FALSE", and the injector skipped that language without an error: "8 of 9 declared language(s)". It now passes handlers that keep yes, no, on, off, y, n, true and false as text. On a 16-page fixture from the handbook's staging site, the old and new injectors write identical pages for the current language list. With `code: no` added, the new one links `../no/basics.html` on every page.
- [ ] **The code shape is still checked before the image runs.** The handbook's `build-deploy.yml` accepts only 2 or 3 lowercase letters for each code and for `main`, before it calls `build_all_chapters.sh`. `read_languages` itself checks presence only, as it did before.
- [ ] **What CI will do on push.** Both files are under `epirhandbook/2.9/common/`, so `epirhandbook-common` changes and every image built on it rebuilds.

---

## 2.9 addendum (2026-09-22): the workflows get a structural linter

- [ ] **`checks.yml` now runs actionlint over the workflow files.** Before, nothing checked them. The planner tests do not cover `build.yml`. The catalog validation has a `yaml.safe_load` parse. That parse cannot see a malformed `uses:` reference, a `needs:` edge to a missing job, a shell fault, or an expression that cannot resolve. On the day the step was added, both workflows passed with actionlint 1.7.7 and with shellcheck 0.9.0 and 0.10.0. So the step started green, with no backlog.
- [ ] **What actionlint does not do.** It checks that a `uses:` reference is well formed, not that the repository exists. A step that names a repository that was never published passes. actionlint reads the workflows and never runs them. Its shell coverage is only what the static rules of shellcheck catch, which is less than "any shell fault".
- [ ] **The step checks that shellcheck is present.** When the shellcheck binary is missing, actionlint turns off its shellcheck rule and still exits 0. Without the check, the step would keep passing while it covered less, and nothing would report it. shellcheck comes from the runner image and is not pinned. actionlint is pinned by version, and the step verifies it against the published SHA-256.
- [ ] **The lint gates publication, and that took a second step.** `build.yml` has no `needs:` on `checks.yml`, and both run on `push`. So on a push to main they run at the same time. A lint only in `checks.yml` catches faults before a merge, but it stops nothing from reaching GHCR. So the lint also runs in the `plan` job of `build.yml`, and every build layer `needs:` that job.
- [ ] **The lint is a script, `.github/scripts/lint_workflows.sh`, and both workflows call it.** The pinned version and its SHA-256 are one fact, and two copies of one fact can disagree. This repository removed one case of that shape when `groups.yaml` went, in the 2026-09-17 addendum below. The script passes shellcheck 0.9.0 and 0.10.0 with no findings.
- [ ] **`description` must now be one line.** The catalog header always said "One line about the image". But validation only needed a non-empty string, so a YAML block scalar passed. The check uses `splitlines()` to decide what a line is. It does not test for `\n` and `\r`. An adversarial review found five separators that ordinary double-quoted YAML escapes can produce: U+000B, U+000C, U+0085, U+2028 and U+2029. A hand-written newline test misses them, and Python counts them as line boundaries. Three tests cover the check, and one of them tests the accepting direction. An OCI label value MAY hold a newline, so this rule is about presentation, not a limit of the format.
- [ ] **What CI will do on push.** `.github/scripts` and `.github/workflows` are both machinery directories. So `changed_images.py` reports every catalog image as changed, and the run plans all nine. The number that republish depends on the run. An image that already carries this SHA from an earlier partial run is skipped. A failure in an earlier layer blocks the layers that depend on it. No catalog content changed.

---

## 2.9 addendum (2026-09-17): brio and archive/ are deleted

- [ ] **`brio` left `common/packages_cran.txt`.** It was added for the config rewriter that 2.9 deleted, and no script in the image loads it. The common list went from 59 to 58 names.
- [ ] **`archive/` was deleted (commit d6d358b).** It held 483 files for the lines 2.5 to 2.8. Git history keeps them. `README.md` says how to read a deleted file back.

---

## 2.9 addendum (2026-09-17): the layout becomes the group membership

- [ ] **What changed here.** All 50 per-chapter package lists moved out of `epirhandbook/2.9/chapters/<stem>/packages_cran.txt`. Each one now sits in the directory of the group image that renders its chapter, as `epirhandbook/2.9/groups/<group>/packages_cran_<stem>.txt`. `epirhandbook/2.9/chapters/` is gone. No byte of any list changed, and all seven generated lists are unchanged.
- [ ] **`groups.yaml` is deleted.** `generate_groups.py` now finds group membership from that layout, not from a file. The design rationale from `groups.yaml` moved into the header comment of the generator.
- [ ] **Why.** Two files stated one fact. `groups.yaml` assigned each chapter to a group, and `images.yaml` lists the chapters that each group image renders. Two statements of one fact can disagree, and then a reader cannot tell which one is true. Now the location of a package list carries the assignment, and `images.yaml` is the only thing left to check it against.
- [ ] **The new check.** `generate_groups.py` compares the layout with the `renders` list of each group image, one group at a time and in both directions. It runs in write mode and in `--check` mode, before it builds any union. One comparison of all stems as a single set would pass a chapter filed under the wrong group, so the comparison is per group.
- [ ] **Why that check cannot use the generated lists.** The `errors` chapter runs no R, so its package list is empty. If you delete that list, or file it under the wrong group, all six group lists and the monolith stay byte-identical. Only the membership check finds the change.
- [ ] **Why the two patterns in the generator anchor with `\A` and `\Z`, not `^` and `$`.** In Python, `$` also matches just before a final newline. So `^content/en/(...)\.qmd$` accepts `'content/en/rmarkdown.qmd\n'`. A `renders:` entry written as a YAML block scalar gives that value, and the membership check must reject it. A comment above the two patterns in `generate_groups.py` says so. This entry records it too, because no committed test covers a block-scalar entry. If someone changes the anchors back, the fault returns and every test stays green. A test fixture would be a stronger guard, but `generate_groups.py` has no test suite, so that is separate work.
- [ ] **Six Dockerfile comments.** The header of each group Dockerfile pointed at `groups.yaml` for its chapter membership. It now points at the `packages_cran_<stem>.txt` files in the same directory. No instruction changed.
- [ ] **Still stale after this change.** The header comment of `epirhandbook/2.9/images.yaml` and one comment in `.github/workflows/build.yml` still name `groups.yaml`. The next step of the same plan owns both.
- [ ] **What CI will do on push.** Each of the six group directories holds a changed Dockerfile and the package lists of its chapters. `changed_images.py` reports all six images as changed. `rbase`, `epirhandbook-common` and `epirhandbook-monolith` are not changed. `generate_groups.py`, the two `README.md` files and the deleted `groups.yaml` all sit at the shared context root, and none of them is a declared build input.

---

## 2.9 addendum (2026-09-10): the per-language layout

- [ ] **What changed here.** The 2.8 line was copied to `archive/epirhandbook/2.8/` (deleted on 2026-09-17, see below) and renamed to `epirhandbook/2.9/`. Every tag, `dir:`, `context:` and `ARG BASE_IMAGE` says 2.9. The nine image names, the six groups and all seven generated package lists are unchanged. The two workflows and the two test files now load `epirhandbook/2.9/images.yaml`.
- [ ] **Why.** The handbook moves each language into its own Quarto book project, `content/<lang>/`, with its own `_quarto.yaml`. The handbook has one root `languages.yml`. The old layout is gone: no `chapters/<stem>.qmd`, no `.<lang>.qmd` infix, no root `_quarto.yml` and no `babelquarto` block. The image line carries the render scripts, so it moves first.
- [ ] **The render scripts.** `build_all_chapters.sh` reads `languages.yml` and renders `content/<lang>/<stem>.qmd`, with the working directory of the container set to that project. It puts each language under `<lang>/`, with a four-line redirect stub at the root. `inject_language_links.R` reads `languages.yml` and swaps the first path segment. `rewrite_lang_config.R` is deleted: each language project already declares its own language, so nothing is left to rewrite.
- [ ] **`renders` entries.** Each entry names the main-language file, `content/en/<stem>.qmd`. The stem is still the last path segment, so this does not change `plan.py --chapter-images`.
- [ ] **brio.** `common/packages_cran.txt` still lists it. It was added for the deleted config rewriter, and no script in the image loads it now. It stays, so that the package set does not change in this rewrite.
- [ ] **What CI will do on push.** `.github/workflows/` and `.github/scripts/` both changed. So `changed_images.py` reports every image as changed, and all nine rebuild and publish under the `2.9` tags. The handbook still pulls `epirhandbook-common:2.8` in four places, so nothing changes on the handbook side until its own cutover.

---

## 2.8 addendum (2026-09-02): the GIS chapter returns

- [ ] **What changed here.** `gis` joined the `analysis` group. Its package list is under `epirhandbook/2.8/chapters/gis/`. The list holds 109 names: the `loadedNamespaces()` of one render that executed, minus base R. For a stem with no 2.7 directory, `generate_groups.py` reads `epirhandbook/2.8/chapters/<stem>/`. It refuses a stem that is in both roots. The analysis list went from 227 to 253 names, and the monolith list from 298 to 320. `epirhandbook/2.8/images.yaml` lists `chapters/gis.qmd` under analysis.
- [ ] **Why not under 2.7.** 2.7 is historical, and nothing new goes there. The generator reads the 49 old chapters from 2.7 because of history. That location is not a rule for new chapters.
- [ ] **Proof before push.** On compute, the analysis image was built from the changed Dockerfile (`FROM ghcr.io/appliedepi/aedockerpublic/epirhandbook-common:2.8`). The build gave BUILD_EXIT=0 and LOAD CHECK OK for all 253 names. The chapter then rendered in that image with `--network none`.
- [ ] **README.** It was rewritten for 2.8. The old text described 2.7 and said that all 51 images were private. Anonymous manifest GETs verified the new text: the nine 2.8 images return 200, and the 2.7 per-chapter images return 403.
- [ ] **What CI will do on push.** `changed_images.py` finds changes in `groups/analysis/` and `monolith/`. So it rebuilds `epirhandbook-analysis:2.8` and `epirhandbook-monolith:2.8`, and republishes both tags in place. `common` and `rbase` are not changed. The handbook push must wait for that publish. If it does not wait, staging fails with a missing-package error.
- [ ] **Round two (PR #1, branch gis-pins).** The babeldown, babelquarto and tinkr pins were removed. brio, fs and xml2 became explicit entries in common, because the render scripts import them. brio had come in only through the removed pins. The codex plan review found this, and `requireNamespace` in the image without the pins confirmed it. appliedepidata was pinned to the sle_hf commit (appliedepidata PR #47), to move to the merge commit before this PR merges. gis was listed under the analysis renders.


---

## Phase 4: productionize (supply-chain controls)

> **This is a historical record, not current documentation.** §8.1 to §8.10 describe this project as it was when each subsection was written, during Phase 4. Later work changed some of what the earlier subsections describe. That work includes the `base_digest` removal in §8.10 and the sweep after it. An inline `[since removed ...]` note marks each passage that this is known to affect. Do not read §8.1 to §8.10 as a description of current behavior. For that, read the field comments in `images.yaml` and the module-header docstrings in `.github/scripts/` (`plan.py`, `build_image.sh`, `changed_images.py`). At the time, the repository README was only a two-line stub.

Phase 4 adds `images.yaml`, manifest-driven CI (`.github/workflows/build.yml` and `nightly.yml`), and a publish path to GHCR. Round 1 of adversarial review **blocked** the first implementation on 4 blockers and 5 more findings. §8.1 to §8.7 record how each was closed. Round 2 **blocked again**, on one supply-chain risk and on parser and documentation findings. The risk was that a token able to write to the registry reached arbitrary package-build code. §8.8 records how each of those findings was closed. Round 1 introduced a vendored YAML reader, `minimal_yaml.py`. It then drew two more rounds of parser findings, and the decision to vendor it was reversed. It is deleted, and hash-pinned PyYAML with a strict schema validator replaces it. §8.9 records that reversal and why. **Status: remediation complete, not yet re-reviewed.** Nothing is published yet, and the first publish has never run.

### 8.1 Publishing happens only from `main`

Both `build.yml` and `nightly.yml` start with a `guard-main-ref` job. Its one step compares `github.ref` with `refs/heads/main`. If they differ, the step runs `exit 1` with an `::error::`. Every other job `needs:` it, directly or through another job. The existing `needs.plan.result == 'success'` check in `plan` already turns a skipped `plan` into a skipped build downstream.

The guard is in the workflow itself. It does not rely only on the `on: push: branches: [main]` filter in `build.yml`, or on a repository setting. An admin can edit or bypass both. `build.yml` also gained `workflow_dispatch`, to carry the `force_republish_frozen` override (§8.3). The guard keeps that safe: a dispatch from a branch fails at once, before checkout runs.

### 8.2 `nightly.yml` no longer publishes anything

[Since removed: `nightly.yml` is no longer in `.github/workflows/`. Check with `ls .github/workflows/`. See the historical-record note at the top of §8.]

The workflow changed from "rebuild every live image and push" to drift detection. It builds every live image, lets the build-time invariants of each Dockerfile run, and then stops.

- **No `packages: write` anywhere in the file.** The top-level permissions are `contents: read`, and no job overrides them.
- **No `docker push` and no `docker/login-action` step anywhere.** `build_image.sh` gained a `verify` mode, next to `publish`. That mode builds and inspects but never pushes. `nightly.yml` calls `build_image.sh` only in `verify` mode.
- **What counts as drift:** does `docker build` still succeed, with every shortcut checked again and not assumed? A base built fresh in this run uses its own fresh local tag. For a base not rebuilt in this run, the build first checks its recorded digest against the registry (§8.6). For `epirhandbook`, a successful build already means that all 473 packages pinned in `renv.lock` resolved, installed and load at their locked versions. That check is the unconditional build-time RUN step of Phase 2 in `epirhandbook/2.5/Dockerfile`, so nightly needs no separate step for it. `rbase` has its own similar invariants: the R version, BLAS/LAPACK and the sha256 of Quarto.
- **Not attempted: a render of real chapter content, compared with a live crawl of epirhandbook.com.** That needs the content of a different repository and a live crawl of the production site of a third party. It is the one-time regression-bar infrastructure of Phase 2 and Phase 3 (`epirhandbook/2.5/verify/`). It is not a job to run every night with nobody watching. A CI runner also cannot run it without the crawl data in git, and this project keeps that data out of git. The full reasoning is in the header of `nightly.yml`.
- **Structural difference from `build.yml`:** one job (`drift-check`), not one job per layer. Nightly builds in sequence on one runner. So it refers to a freshly built base by its plain local Docker tag, with no registry round trip, because nothing is pushed. This also removes the layer-count limit for nightly: it walks the layers of `plan.json` with `jq`, however many there are. `build.yml` still has the static limit, which is now a hard failure in `plan.py` (§8.6).

### 8.3 `frozen: true`: a published version never moves by accident

Both `rbase` and `epirhandbook` are marked `frozen: true` in `images.yaml` (see the comment on that field). In `publish` mode only, `build_image.sh` checks each tag of a frozen image before it pushes that tag. It uses `docker buildx imagetools inspect` to find out whether the tag already exists in the registry. If it does, the script refuses with `exit 1` and an `::error::` that names the image and the tag. The exception is an image whose name is in `FORCE_REPUBLISH_FROZEN`. That variable comes from the `workflow_dispatch` input `force_republish_frozen` in `build.yml`. It means that a human, who dispatched the run by hand, wants to replace the tag. Automation never sets it. `nightly.yml` has no such input and cannot push at all.

The full path was verified against a real local registry on compute (`registry:2` at `localhost:5000`), with the real `build_image.sh` and no stand-in. A first publish of a fresh tag succeeds. A second publish of the same tag is refused (exit 1). A third, with the override set, succeeds (exit 0).

**Round 2 update (§8.8):** this check now also runs on its own, as a separate `build.yml` step before `docker/login-action` and `docker build`. The inline check in `publish` mode, described above, is unchanged and still runs.

### 8.4 Supply-chain pins

- **Each third-party action is pinned to a full commit SHA**, with the version in a trailing comment. The versions came from the live GitHub API.
  - `actions/checkout@11d5960a326750d5838078e36cf38b85af677262`: v4.4.0
  - `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065`: v5.6.0
  - `docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9`: v3.7.0
  - `nick-fields/retry@ce71cc2ab81d554ebbe88c79ab5975992d79ba08`: v3.0.2

  Each action is pinned to the major-version tag that was already in use (v4/v5/v3/v3). This is a supply-chain fix (mutable tag -> immutable SHA), not a version bump.
- **`pip install pyyaml` removed, not hash-pinned. REVERSED, see §8.9.** The shape of `images.yaml` is small and this project owns it (see its header for the field list). So `.github/scripts/minimal_yaml.py` was a vendored reader for that shape only. It supported a block sequence of flat mappings, schema-validated keys, and strictly-cased quoted, bare, null and bool scalars. It also supported one level of inline flow sequence that respects quotes, and comments. It raised `ValueError` on anything else, so that it would not misread input in silence. It was compared byte for byte with `yaml.safe_load()` on the real file. `TestMinimalYaml` in `test_plan.py` tested it. Those tests caught a real bug during development. An early version accepted an indent of at least 4 spaces as a continuation line. That version would have flattened a nested value in silence, where it had to reject it. The fix accepted only an indent of 4 spaces. **The claim "raises on anything else" was false when it was written.** Round 2 review found four confirmed cases where the parser misread input and did not reject it. The worst was `live: False`, with a capital F. It parsed as the truthy *string* `"False"`, so the reader included an image that the catalog excluded. Round 3 and round 4 each found more such cases (see §8.9). **§8.9 reverses the decision in this bullet.** `minimal_yaml.py` is deleted, not patched a fifth time. PyYAML is now the parser, hash-pinned in `.github/scripts/requirements.txt`, with a strict `validate_catalog()` allowlist schema on top. §8.9 gives the full reasoning and lists what replaced each test that this bullet named.
- **`packages: write` only on the jobs that push** (`build-layer-0..3` in `build.yml`). Every other job gets the workflow-level `contents: read` default and nothing more. Those jobs are `guard-main-ref`, `plan` and all of `nightly.yml`.
- **The package-build step never gets a credential that can write to the registry.** `GITHUB_PAT` goes to `docker build` as a BuildKit secret. Its only use is to raise the GitHub API rate limit for pak while pak resolves the 7 GitHub-pinned packages of epirhandbook. In both `build.yml` and `nightly.yml`, its value comes from `GH_READONLY_PAT`, never from `secrets.GITHUB_TOKEN`. `GH_READONLY_PAT` is a dedicated repository secret: a fine-grained PAT scoped to **public read only**, with no `packages: write` and no repository write of any kind. This was the round 2 blocker. §8.8 has the full account and the verification on compute.

  **To create or rotate `GH_READONLY_PAT`:**

  1. Go to GitHub -> Settings (personal) -> Developer settings -> Fine-grained personal access tokens -> Generate new token.
  2. Set the resource owner to the token owner. The owner does not need org membership beyond what reading public content needs.
  3. Set repository access to Public Repositories (read-only). That is enough, because the token only raises the anonymous GitHub API rate limit for 7 package repositories that are already public. It gives access to nothing private.
  4. Give no permission `write`.
  5. Save the token at repository Settings -> Secrets and variables -> Actions -> New repository secret, with the name `GH_READONLY_PAT`.

  If the secret is not configured, the build runs with no token at all. It never falls back to `secrets.GITHUB_TOKEN`. The only effect is that those 7 lookups use the anonymous GitHub API rate limit. All jobs on the same GitHub-hosted runner IP share that limit at that moment.

### 8.5 Publish gate

- **`main` only.** See §8.1.
- **`.github/CODEOWNERS`** covers `.github/**` and `images.yaml`, with the owner `@raubreywhite`. The owner was checked with the GitHub API against the real commit history of `appliedepi/aedockerpublic`. CODEOWNERS takes effect only when "Require review from Code Owners" is on, for a rule that covers `main`. The header of the file says where to turn it on.
- **A `publish` GitHub Environment is set on each job in `build.yml` that pushes** (`build-layer-0..3`). **To require a reviewer:** go to repository Settings -> Environments -> New environment, and name it `publish`. Then go to Environment protection rules -> Required reviewers, add yourself or a team, and save. Until then, `environment: publish` has no effect. The first time a run names an environment that does not exist, GitHub creates it with no protection rules. This project does not assume that the gate is on.
- **Not done: pull requests are not forced, and admin bypass is not removed.** Direct pushes to `main` are an informed choice (see the "Repo state" note under "Phase roadmap and status" on the earlier branch-protection bypass). **Residual risk:** a change to a workflow file can change what is published in the same push that introduces it. Nothing here reviews a workflow diff before it takes effect on its own next run. The required-reviewer gate of the `publish` environment is the mitigation, once it is on. It puts a review step between the push of the code and the execution of `packages: write`, whatever the workflow file now says. The gate is off by default, and this project has not turned it on.

### 8.6 Planner hardening

- **An unknown `base:` name is now a hard error.** Before, the topological sort saw a typo (for example `base: rbse:4.3.2`) the same as "this image has no base", because both are "not in `remaining`". The image then built as if it had no base, with no error. Its cascade edge (rebuild me when my base rebuilds) then never fired again, also with no error. Now `topological_order()` validates every `base:` against the full catalog before it sorts. It raises `ValueError` and names the image, the bad name and the known good names. The test is `test_unknown_base_name_is_a_hard_error` in `.github/scripts/test_plan.py`. It was shown red and then green during development.
- **A catalog deeper than 4 layers is now a hard error, not a silent partial publish.** `MAX_SUPPORTED_LAYERS = 4` in `plan.py` matches the `build-layer-0..3` jobs in `build.yml`. `topological_order()` raises `ValueError` if the real catalog ever needs a 5th layer. Today this cannot happen (2 images, 2 layers). It becomes a real risk once Phase 5a adds about 50 chapter images. The test is `test_catalog_deeper_than_max_layers_is_a_hard_error`, which uses a synthetic chain of 5 images.
- [Since removed: this whole guard, the `base_digest` field and the comparison below, no longer exists. See §8.10.]
- **A stale `base_digest` is now caught before the build uses it.** The steady-state branch of `build_image.sh` runs when the base was not rebuilt in this run. There, the script queries the floating tag of the base live. It compares the result with the recorded `base_digest` before it builds on that base. If they differ, it runs `exit 1` and names both digests and the `images.yaml` field to update. This was verified against a real local registry (`registry:2` on compute, `localhost:5000`). When the digests agree, the script exits 0 and continues. When they differ, it exits 1 with that message.

### 8.7 Concurrency and SSH hardening

- **The concurrency group does not depend on the ref** (`aedockerpublic-ghcr-builds`, with no `-${{ github.ref }}` suffix) in both workflows. So a dispatch from any ref waits for every other run that can change these images, not only for runs on its own ref.
- **`sshd_hardening.conf` gained** `AllowTcpForwarding no`, `X11Forwarding no`, `PermitTunnel no`, `GatewayPorts no` and `AllowAgentForwarding no`. The existing build-time `sshd -T` assertion in the Dockerfile now checks all five in the effective config, not only in the source file. A real rebuild of `rbase` on compute verified it: `sshd -T` reports all 9 hardening settings in effect (the first 4 and these 5).

### 8.8 Round 2 remediation: token privilege and parser strictness

Round 2 of adversarial review blocked on one supply-chain risk, and on parser and documentation findings.

**Blocker: the build received a token that could write to the registry.** The `build-layer-N` jobs of `build.yml` hold `packages: write`. They used to set `GITHUB_PAT: secrets.GITHUB_TOKEN` on the "Build and push" step. That gave `docker build` a token that can push to `ghcr.io/appliedepi/aedockerpublic/`. In that build, `Rscript pak_install.R` of `epirhandbook/2.5` downloads and compiles 473 packages, and several of them run their own post-install scripts. Arbitrary package-build code must never hold a credential that can publish. The fix:

- `GITHUB_PAT` now comes from a new repository secret, `GH_READONLY_PAT`. It is a fine-grained PAT scoped to public read only, with no `packages: write` and no repository write. The `build-layer-N` jobs of `build.yml` and the `drift-check` job of `nightly.yml` both use it. The `GITHUB_TOKEN` of nightly was already read-only in practice (`contents: read`), because nightly never raises its permissions. It changed too, so that both workflows give the same package-build code the same kind of credential for the same purpose. Otherwise the token would depend on which workflow ran the code. `secrets.GITHUB_TOKEN` stays for its own valid uses: `docker/login-action` and the later `docker push`.
- If `GH_READONLY_PAT` is not configured, the env line `GITHUB_PAT: ${{ secrets.GH_READONLY_PAT }}` gives an empty string. GitHub Actions does not error on an undefined secret reference. No `||` fallback to `secrets.GITHUB_TOKEN` exists anywhere, so no code path can give the write-capable token to the build. `build_image.sh` treats an empty or unset `GITHUB_PAT` as "build with no token". It still passes `--secret id=github_pat,env=GITHUB_PAT`, because BuildKit accepts an empty secret. pak then uses `github::` to resolve the 7 GitHub-pinned packages under the anonymous GitHub API rate limit, not an authenticated one. Both workflow headers and §8.4 above document this.
- Verified on compute. `build_image.sh verify`, which needs no push or login, built `epirhandbook` FROM the existing local `rbase:4.3.2`. `GITHUB_PAT` was explicitly unset, and the Docker layer cache was off (`--no-cache`). The cache had to be off because BuildKit leaves the value of a secret out of its cache key. A plain rerun would then reuse the earlier cached result and prove nothing. All 473 packages still installed, and the version and load check still passed. `Config.Env` and `docker history --no-trunc` both showed zero occurrences of any token. The returned evidence of the round 2 remediation session has the build log tail and the grep counts.
- **The frozen-tag check now runs before `docker build` and before `docker/login-action`,** not only before `docker push`. `build_image.sh` gained a `check-frozen` mode. It takes only the repo, name, tags and frozen values, with no base information and no docker build. `build.yml` now runs it as its own step before the login step, in every `build-layer-N` job. So a republish that must fail (frozen, tag already published, no `force_republish_frozen` override) is refused earlier. The refusal now comes before the job gets the registry-push credential through `docker/login-action`, and before the compile of about 45 minutes. The same check (the same `check_frozen_or_die` shell function) also still runs inline in `publish` mode, before base resolution. It stays there so that `build_image.sh` works on its own. A human can run it directly in `publish` mode, as the local-registry rehearsal in §8.3 does. That run still gets the refusal, whatever the step order in `build.yml`.

**Parser findings: `minimal_yaml.py` misread valid YAML with no error.** The claim in §8.4, "raises on anything outside it", was false when it was written. There were four confirmed cases, and each one is now a hard error:

1. `live: False` (capital F) parsed as the string `"False"`. That string is truthy in Python, so the reader included an image that the catalog excluded. This was the worst kind of failure: valid YAML, the opposite meaning, and no error. Now only lowercase `true`, `false` and `null` are typed scalars. Any other casing is a hard `ValueError` that names what it found.
2. `tags: ["a,b"]` split on the comma inside the quotes. `tags: ["1",]` gave `["1", null]` with no error. The flow-sequence parser now scans one character at a time and respects quotes, so a comma inside quotes never splits. An empty item (a trailing or doubled comma) is a hard error, never a null.
3. The quote state flipped on each quote character, with no escape rules. So a backslash in a quoted value (for example an escaped quote) was handled wrongly and not rejected. Any backslash inside quotes is now a hard error. This applies in comment removal, key/value splitting, scalar parsing and flow-sequence parsing.
4. An unknown per-image key (for example the typo `froze: true`) was accepted with no error, and the correctly spelled `frozen` key was then absent. `plan.py` then used its default `False`, so the typo took effect with no error. `minimal_yaml.py` now validates each image against a schema. An unknown key is a hard error. The allowed keys are `name`, `dir`, `tags`, `base`, `base_digest`, `live` and `frozen`. `name`, `dir`, `tags`, `base` and `base_digest` must all be present. `live` and `frozen` stay optional, to match the `.get(key, default)` fallback in `plan.py`.

New tests in `TestMinimalYamlRound2Hardening` in `test_plan.py` cover all four cases. There are 7 tests, because cases 1 and 2 each get a positive and a negative test. Before the fix, all 7 were shown red against the parser, each for the stated reason. For example, the silent-acceptance cases failed with "ValueError not raised", and the comma-splitting case failed with a wrong list value. After the fix, all 7 were green. `minimal_yaml.py` still parses the real `images.yaml` byte for byte the same as `yaml.safe_load()`.

**Two documentation overclaims, both corrected:**

- The `minimal_yaml.py` bullet in §8.4 now says that the "raises on anything outside it" claim was false when written, and points here.
- The comment on the `frozen:` field in `images.yaml` said that a frozen image "is published ONCE, deliberately, by a human triggering build.yml". But `build.yml` also publishes on an ordinary push to `main`, not only on a run that a human dispatches. The corrected comment says that the first run of `build.yml` to reach a tag publishes the frozen image, once, on a push or a dispatch. The only one-time human action is the `force_republish_frozen` override, which replaces a frozen tag that is already published.

### 8.9 Vendored-parser reversal: hash-pinned PyYAML replaces `minimal_yaml.py`

`minimal_yaml.py` started in round 1. It closed a finding about an unpinned `pip install pyyaml`: a narrow vendored reader replaced a package fetched from the network. The reader then drew three more rounds of adversarial review. Each round found a new case where the reader gave a different meaning from real YAML. Its docstring claimed that it rejected everything outside its supported subset, and that was never true:

- **Round 2** (§8.8): four confirmed cases. A capitalized `False` parsed as the truthy string `"False"`. A comma inside quotes (`["a,b"]`) split into two tags. A backslash in a quoted value flipped the quote state wrongly and did not raise. An unknown per-image key (`froze` for `frozen`) was accepted with no error.
- **Round 3**: the other YAML boolean aliases, `yes`, `no`, `on` and `off` in any casing, were not rejected either. An unquoted `live: no` parsed as the truthy string `"no"`. This is the same failure class as the round 2 `False`, with a different spelling.
- **Round 4**: a `#` directly after a value, with no space before it, was cut off as a comment. Real YAML keeps it as part of the scalar. A bare numeric scalar (`tags: [2.5]`) stayed the string `"2.5"`, where real YAML gives a float, and the reader did not raise. A duplicate key in one image kept the last value and did not raise.

Four rounds of adversarial review blocked on the same decision: how to read `images.yaml`. That is a pattern. The contract of the vendored reader, "the same meaning as real YAML, or raise", has no bound. YAML has a large implicit scalar grammar: dates, times, hex, octal, sexagesimal, several spellings of boolean, several of null, and more. That grammar is larger than any hand-written rejection list. So each round found a construct that the list did not yet cover. A fifth patch to the list would not close that gap. It would only move the next gap.

**The decision is reversed.** `minimal_yaml.py` is deleted, not patched again. `plan.py` now uses real PyYAML (`yaml.safe_load`) to parse `images.yaml`, and a strict allowlist schema, `validate_catalog()`, to check the result. Each field has one declared type. Anything else is a hard `ValueError` that names the file, the image, the field and the expected value:

| Field | Rule |
|---|---|
| top level | a mapping whose only key is `images`, which maps to a non-empty list |
| `name` | non-empty `str` matching `^[a-z0-9][a-z0-9._-]*$` (safe for an image name) |
| `dir` | non-empty `str`; relative path (no leading `/`, no `..` segment) |
| `tags` | non-empty `list`; every element a non-empty `str` |
| `base` | `null`, or a non-empty `str` |
| `base_digest` | `null`, or a `str` that fully matches `^sha256:[0-9a-f]{64}$` |
| `live` / `frozen` (optional) | a real `bool` (`isinstance(x, bool)`). A quoted `"true"` is a `str` and is rejected |
| any key not in `{name, dir, tags, base, base_digest, live, frozen}` | hard error |

[Since removed: `base_digest` and `frozen` are both gone from `ALLOWED_IMAGE_KEYS` in `plan.py`. §8.10 covers the `base_digest` removal. This document does not describe the removal of `frozen` separately.]

This design has a bound, and the vendored reader did not. PyYAML is a complete YAML implementation, so it already resolves each implicit scalar correctly, and no rejection list needs to grow. The schema states, once per field, the one type that field may have. Whatever a future YAML construct resolves to, it matches that type or it is rejected, so no gap remains to find later. This is how the schema catches `tags: [2024-01-01]`. `validate_catalog()` does not need to know that PyYAML turns an unquoted date into a `datetime.date`. It only needs to know that a tag must be a `str`, and a `datetime.date` is not one. The same rule catches `tags: [2.5]` (a `float`), and any other numeric or timestamp form that YAML resolves in the future.

**PyYAML is hash-pinned.** That closes the original round 1 finding in the way the finding asked, where vendoring had only avoided it. `.github/scripts/requirements.txt` pins `PyYAML==6.0.3`, the current stable release on PyPI at the time. The `--hash=sha256:...` lines came from the PyPI JSON API. They cover the sdist and the manylinux x86_64 wheels for CPython 3.9 to 3.14. That covers the GitHub `ubuntu-latest` runner, whichever "3.x" `actions/setup-python` resolves at run time. Both `build.yml` and `nightly.yml` install it with `python -m pip install --require-hashes -r .github/scripts/requirements.txt`. The step runs after `actions/setup-python` and before the unit tests of the planner. pip refuses a downloaded artifact that does not match a recorded hash, and never installs it. Verified on bench: an install into an isolated `--target` directory with the real hash succeeds. The same install with one hash character set to zero is refused (`THESE PACKAGES DO NOT MATCH THE HASHES`).

**Tests.** One `TestValidateCatalog` class replaces four classes in `test_plan.py`: `TestMinimalYaml`, `TestMinimalYamlRound2Hardening`, `TestMinimalYamlRound3BooleanAliases` and `TestMinimalYamlRound4`. All four were specific to the deleted parser. The new class has 16 tests. Each test passes a real YAML string through `yaml.safe_load()` and then `plan.validate_catalog()`. Together they cover every row of the table above. The other tests are unchanged, because none of them depends on how the catalog is parsed. They are the cascade and planner logic in `RequiredCases` and `ExtraCases`, and the `TestAgainstRealCatalog` canary. The full suite has 32 tests, and all pass. Two red-then-green demonstrations ran during development:

1. With the real-bool check for `live` and `frozen` turned off, only the two tests that assert it failed, both with `ValueError not raised`.
2. The `base_digest` regex was weakened to accept anything. Then only the one test that asserts the rejection of a malformed digest failed, also with `ValueError not raised`.

Both breaks were restored and checked to be byte-identical to the working version, and the full suite passed again.

**Status: implemented, not yet re-reviewed**, as for round 2 before it. This change closes a review finding, but adversarial review has not yet seen the change itself. Nothing is published yet, and the first publish has never run.

### 8.10 `base_digest` retired: the optional cross-check had no effect

The OCI-revision change model (§8.2/§8.6) already made `build_image.sh` resolve the digest of every base image live from the registry, on every build. If the base was rebuilt in the same run, the digest comes from the image that the run just pushed. If not, it comes from the published tag of the base. That live resolution always runs. `base_digest` was already demoted (§8.6, and the field table in §8.9) to an optional cross-check. It fired only in the one branch where the base was not rebuilt in this run. Even there, it compared against the digest that the live resolution had already fetched. So the field could never change the outcome of a build. A human also had to update it by hand after each base rebuild, with the old Digest-pinning procedure that the list below names. The field cost maintenance and gave no safety property, so it is removed. `frozen` got the same treatment when the OCI-revision model made its guard redundant. The field is gone from the live catalogs and the code. Its historical description in §8.6, §8.8 and §8.9 above stays as written. Those sections record what was true during Phase 4, not what is true now.

Removed:

- **`images.yaml`** (root):
  - the entry for `base_digest` in the `Fields:` doc block;
  - the "Digest-pinning procedure" comment block, about 45 lines on the old manual way to record a pin;
  - the one `base_digest: null` row for `rbase`.

  The "read by" comment of the file no longer claims that anyone reads it "to know the current base_digest pin". Nobody did, because the field did nothing.
- **`epirhandbook/2.7/images.yaml`**: `base_digest: null` removed from all 50 rows. CI reads this catalog, so it stays schema-valid at each step.
- **`.github/scripts/plan.py`**: `base_digest` removed from `REQUIRED_IMAGE_KEYS` and `ALLOWED_IMAGE_KEYS`. Also removed: the two validation checks for it (digest format, and "digest without a base is meaningless"), and `DIGEST_RE`, which nothing else used.
- **`.github/scripts/build_image.sh`**: the `BASE_DIGEST` positional argument, the steady-state comparison against it, and every stale comment that pointed at the deleted procedure in images.yaml. Each positional after the removed one moves down by one. `BASE_FRESH` was `$8` and is now `$7`. `GIT_COMMIT` was `$9` and is now `$8`. `CONTEXT` was `${10}` and is now `${9}`. The four `build_image.sh publish` call sites in `build.yml` changed to match.
- **`.github/workflows/build.yml`**: `matrix.image.base_digest` removed from all four build-layer calls.
- **`.github/scripts/test_plan.py`**: `base_digest` removed from every fixture and inline YAML string. Four tests are deleted, because their only subject was a field that no longer exists: `test_short_base_digest_is_rejected`, `test_real_64_hex_digest_is_accepted`, `test_null_base_digest_is_accepted` and `test_base_digest_without_a_base_is_rejected`.
- **`epirhandbook/2.7/generate.py`**: the line that wrote `base_digest: null` into the generated catalog. This mattered although the generator was due for archival: the allowlist in `plan.py` would reject a generated catalog that still had the old field.
- **`epirhandbook/2.7/common/Dockerfile`**: the comment on the `BASE_IMAGE` ARG pointed at the deleted procedure. It now describes what resolves the ARG: the live base-resolution block in `build_image.sh`.

**Not changed**: `epirhandbook/2.5/Dockerfile`, `epirhandbook/2.6/README.md`, `epirhandbook/2.6/generate.py` and `epirhandbook/2.6/images.yaml` (50 rows, all with `base_digest: null`) still name the retired field. That tree is frozen provenance, and no CI path loads it. `build.yml` passes only `--images-yaml images.yaml --images-yaml epirhandbook/2.7/images.yaml` to `plan.py`. So that tree stays as it is, and this is correct.

**Causally-red probe**: one `base_digest: null` line, added back to `epirhandbook/2.7/images.yaml`, made `plan.py` fail at once against both live catalogs. The error names `base_digest` as a key not in `ALLOWED_IMAGE_KEYS`. This proves that the allowlist rejects the removed field, and does not only stop requiring it.

**Status: implemented, not yet re-reviewed**, as for each entry before it in this section.

---

## Phase roadmap and status

One variable changes per phase. Every phase after Phase 1 is regression-tested against the Phase 1 render.

| Phase | What changes | Status |
|---|---|---|
| **1: Bare reconstruct** | `rocker/r-ver:4.3.2` + sysdeps + Quarto 1.4.550 + `renv::restore()`. No custom base and no pak. This phase sets the known-good baseline render. | **Done**, commit `017fdbe` |
| **2: Factor + pak rehearsal** | Split into `rbase/4.3.2` + `epirhandbook/2.5`. Replace `renv::restore()` with **pak**, from the same lock pins. The render must be identical to Phase 1. | **Done**, commits `bfec633`, `59ed133` |
| **3: Per-chapter rendering** | Render each chapter **on its own** on the full 473-package image. Only the render *granularity* changes, not the package set. Record the real package footprint of each chapter. | **Done**, codex passed on round 6 |
| **4: Productionize** | `images.yaml` catalog, manifest-driven CI (selective + cascade + nightly), publish to GHCR, optional SSH runtime toggle. Same content, same two images. | **Code complete, codex PASS on round 8, committed locally as `1dd7960`. Not yet pushed or published.** Rounds 1 to 7 each found a real supply-chain or schema defect. After four rounds of differences in the hand-written reader, hash-pinned PyYAML and a strict schema replaced the parser (see §8). The first GHCR publish runs on the first push to main, and it needs explicit approval from Richard. `GH_READONLY_PAT` is optional. The build works with no token, and the PAT only raises the anonymous GitHub API rate limit for the 7 GitHub-pinned packages. Add it only if a CI run hits the limit. |
| **5a: Split, same packages** | Build `epirhandbook-common` + 50 thin per-chapter images, on the **frozen 4.3.2 stack**. Package versions do not change. | **Done**, codex PASS on round 5, committed `beec92f`, not pushed |
| **5b: Modernize** | Modern `rbase/4.6.0` + a minimal forward port of the frozen content to 2026 packages, published as **2.7**. The topology does not change. | Not started |

**Repo state:** pushed. `origin/main` is at `e119c7f`, and local and remote match. The push bypassed a branch-protection rule on `appliedepi/aedockerpublic` ("Changes must be made through a pull request"). Admin permissions allowed it, and GitHub recorded it as a bypass. Decide whether future work on this repository goes through a PR.

### Why 3, 5a and 5b are separate

Each phase asks a different question. Separate phases make it possible to attribute a failure to one cause.

- **Phase 3** asks *"can a chapter render alone?"* It answers on the monolith, so the package set is not a variable.
- **Phase 5a** asks *"can a chapter render on a minimal package set?"* It answers on the frozen 4.3.2 stack, so the package **versions** are not a variable. A failure here means that the footprint was wrong, and nothing else.
- **Phase 5b** asks *"does this content still work on 2026 packages?"* It answers with no further change to the topology.

**Phase 5 was first one phase, and that was a mistake.** It changed two major variables at once: package versions (2024 → 2026) *and* image topology (one monolith → about 50 thin images). If a chapter failed to render, the cause would be unclear. It could be a wrong footprint or a package that changed, and nothing could tell which.

The order matters as much as the split. **5a must come before 5b.** The success bar for 5a is "renders identically to the Phase 3 monolith render". That frozen reference exists only while the packages stay pinned at 4.3.2. If modernization came first, the reference would be gone, and the footprints would ship with no test against anything.

### Success bars

| Phase | Bar |
|---|---|
| 5a | Each chapter renders on its minimal image **identically to its Phase 3 monolith render**. The Phase 3 comparators (`compare_chapters.py`, `compare_assets.py`, `compare_widgets.py`) measure this, with no change to them. |
| 5b | **Size of the source diff**: as few changes as possible. This bar is not output equivalence. Two years of newer packages render differently, and where an API changed, the source must change. |

---

## The problem

`github.com/appliedepi/aedockerpublic` will host the Docker images for Applied Epi products. The first job is to stabilize **epiRhandbook**, which had not compiled for a long time.

The cause is a tightly pinned 2024 stack that no longer matches any current default toolchain:

- The handbook pins **R 4.3.2**, **Bioconductor 3.18** and **Quarto CLI 1.4.550**, on **Ubuntu jammy**.
- Its `renv.lock` pins **473 packages** (463 CRAN + 3 Bioc + 7 GitHub).
- `ggtree`/`treeio` need Bioc 3.18, which ties the build to R 4.3.
- Each chapter loads its own packages with `pacman::p_load()`. When renv is not restored, `p_load` reaches live CRAN and installs the current version. That breaks the pinned stack with no error.
- The build uses **Quarto + babelquarto** (9 languages), not bookdown.

The strategy is to first reproduce the old environment in full, so that the **unchanged** content renders. Only then does modernization start.

---

## The 2.5 to 2.8 maintenance notes (moved from README.md on 2026-10-05)

These notes stood in `README.md` until 2026-10-05. They describe the renv-locked 2.5 build on `rbase:4.3.2`, and most no longer apply.

This part is for the maintainer of the image lines. A contributor who uses the images does not need it.

#### Which content, and which reference

Two versions of the handbook content exist. Do not mix them.

| Content | Where | Role |
|---|---|---|
| **Sep-18-2024** (`epiRhandbook_eng` commit `c3cbc76`) | live at `https://www.epirhandbook.com/en/` | **The frozen baseline. This is the version we reproduce.** |
| **Jan-2025 drift** (branch `richard` @ `e121efa`, and `deploy-preview`) | not published | **Parked.** An unpublished content update of 52 chapters. We review it only at the end, to keep any useful parts. |

The reproduction target is a **new crawl of the live site**. Do not use the `html_outputs/` committed in the repo: it is stale, so it is not a valid reference.

- Live crawls on compute: `~/ae/live_crawl` (English) and `~/ae/live_crawl_ml/<lang>` (7 languages).
- Sep-18 render source on compute: `~/ae/render_sep18`.
- The regression bar is `epirhandbook/2.5/verify/manifest.tsv`. It holds a per-page text similarity and a `sha16` content hash. Regenerate it with `epirhandbook/2.5/verify/make_manifest.py`.

**The manifest means "same output" only when package versions match.** It is the bar for Phase 2 and Phase 3. It is **not** the bar for Phase 5, where newer packages can render differently for valid reasons.

#### Design decisions, and why

- **`rbase`, not `base`.** The name leaves room for a separate `pythonbase` later. It also matches the existing `ghcr.io/niphr/cs/rbase`.
- **We own all of `rbase:4.3.2`.** It is `FROM ubuntu:jammy` (digest-pinned) plus R 4.3.2 from **Posit r-builds**, with **no rocker**. We chose control and consistency over lower maintenance.
- **The image installs openblas 0.3.20 on purpose.** It is the BLAS that rocker links. Because it matches, the removal of rocker changed no computed numbers. A different BLAS would change values in many chapters.
- **The lock controls pak, and pak chooses nothing.** `renv.lock` stays the single source of truth. The installed version is always the pin. The *ref form* changes only how pak fetches each package.
- **CRAN is `cloud.r-project.org` source, not PPM.** Phase 2 restores a lock whose pins span many dates, so no single PPM snapshot contains all of them. Only cloud has every archived version.
- **`GITHUB_PAT` is a BuildKit secret.** Do not use `--build-arg` with `ENV`. That puts the token into the image's `Config.Env`, and `docker inspect` or a push exposes it.

#### Traps already found

Use these findings. Do not derive them again.

- **pak's SAT solver and R 4.4.** A plain `pkg@version` ref fails for 15 packages. pak checks the R constraint of the *current* release, even when an *older* version is pinned, and reports a false dependency conflict. The fix is `url::` refs that point to the CRAN Archive tarball, which bypass the solver. renv does not have this problem, because renv does not solve: it installs the pin.
- **pak install order.** `dependencies = FALSE` resolves correctly but drops build-order edges. A source package can then build before its own build dependency (RcppRoll before Rcpp). `dependencies = NA` restores the order but turns the solver back on. The fix is a **topological layer install**:
  1. Build the graph from the lock's own `Requirements`.
  2. Kahn-sort it into 15 layers.
  3. Install each layer with `dependencies = FALSE`.
- **Bioconductor drift.** The lock pins `ggtree` 3.10.0, but the live contrib directory of Bioc 3.18 now serves 3.10.1. Only the Bioc Archive still has 3.10.0.
- **pak leaves about 4 GB of build scratch in `/tmp`.** Delete it in the *same* `RUN` layer. If you do not, the image doubles in size (9.5 GB against 5.1 GB).
- **Docker tag races.** When two builds tag the same image name, the last to finish wins, so a bad build can overwrite a good one. Run builds that share a tag one after the other.
- **Two render failures are not caused by the image.** `plot_continuous` does not call `library(tidyr)`, and it is an unused `.qmd`. `gis` fetches live OpenStreetMap tiles at render time, which stops the whole book. So `gis` is commented out of `_quarto.yml` for rendering.
- **Render into a writable copy.** `render_book()` deletes `html_outputs` first.
- **Linux needs the filename-case shim.** Run `python3 fix_image_case.py <source>` before you render.

#### How we work on this

- **Build on compute.** bench has no Docker. Rsync the build context to `compute:~/ae/ehb_build`, then run `docker build` over SSH.
- **Check the built image, not only the Dockerfile.** After every build, run `docker inspect <img> --format '{{.Config.Env}}'` to confirm that the image holds no token. A review of the source alone, codex included, does not find a secret in the image.
- **Execution model:** opus orchestrates and writes the brief. sonnet implements. A *new* sonnet runs the objective check again and returns raw evidence. opus makes the decision.
- **codex is the phase gate.** A phase is done only when codex signs off. codex examines soundness ("what is not really pinned"). It does not examine the render, because the render check is objective and already measured.
- **The gate is per phase, not per build iteration.** Claude runs the short build loop, and we spend the codex quota with care.
