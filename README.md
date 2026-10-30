# aedockerpublic

This repository builds and publishes Applied Epi's Docker images to `ghcr.io/appliedepi/aedockerpublic`. It holds a shared R base image, one catalogue per project, and the CI that decides which images to rebuild. [`CHANGELOG.md`](CHANGELOG.md) is the historical record.

## Projects

| Project | Documentation |
|---|---|
| Epi R Handbook | [`epirhandbook/README.md`](epirhandbook/README.md) |

Every project builds FROM the shared base image, `rbase`.

## Layout

| Path | Holds |
|---|---|
| `images.yaml` | The catalogue of shared images. |
| `rbase/<R version>/` | The `rbase` Dockerfile. |
| `<project>/<version>/` | One project line: its Dockerfiles, package lists, scripts and its own `images.yaml`. |
| `.github/scripts/`, `.github/workflows/` | The planner, the build script and the two workflows. They serve every project. |

Older lines are not in the working tree. They are in git history. `git log --diff-filter=D --name-only -- <path>` finds the commit that removed a path, and `git show <sha>^:<path>` reads a file back.

## rbase

R on a digest-pinned Ubuntu, with a dated CRAN snapshot and no R packages. It holds the system libraries that R packages commonly need, including GDAL, GEOS, PROJ and a JDK for **rJava**. Its tag is `<R version>-<CRAN snapshot date>`, and the current tag is in the root `images.yaml`. It is FROM an external image, so it has no base in the catalogue.

**The rbase tag is mutable.** Each rbase rebuild overwrites it in the registry. The date names the CRAN snapshot that the image was built against. It does not mean that the image bytes are frozen. Reviewers can read "date-pinned" as "immutable" and report a supply-chain defect. That report is declined by design. For byte-immutability in a particular build, pin the digest at the point of use.

**Update the R version or the CRAN snapshot.** Change the rbase tag in `images.yaml` (`<R version>-<YYYY-MM-DD>`). **Do not write the date anywhere else.** The tag is the single source of truth, and the build derives the snapshot URL from it. This change rebuilds `rbase` and cascades to every live image of every project.

## The catalogue

The catalogue is the root `images.yaml` plus each project's `images.yaml`. The planner loads them together, so a project image can be FROM `rbase`. All files are maintained by hand. The header comment of the root `images.yaml` holds the authoritative field rules.

Each record has four required fields:

- `name`: the image name.
- `description`: one line about the image. The planner rejects a record without one, because an image with no `description` publishes its base image's description.
- `tags`: the tags to publish.
- `base`: the image in the catalogue that this image is FROM, or `null`. The `base` edge drives the cascade.

These fields need more explanation:

| Field | Meaning |
|---|---|
| `dir` | This image's own files: where its Dockerfile lives, and its change-detection scope. |
| `context` | The `docker build` context, when it differs from `dir`. Use it when several images COPY shared files from a common root. Change detection stays per image. |
| `live` | `true` means a rebuild of `base` cascades to this image. `false` stops only that automatic cascade. A direct edit to the image's own `dir` still builds it. |
| `renders` | Optional. The `.qmd` files this image renders. See "Project hooks". |

## Trigger and change detection

**CI builds on a push to `main`, or on a manual rerun (`workflow_dispatch`) from `main`.** There is no nightly build and no scheduled run.

`.github/scripts/changed_images.py` decides what to rebuild. For each catalogue image, it reads the `org.opencontainers.image.revision` OCI label of the **currently published** image. It reads the label with `docker buildx imagetools inspect`, which reads metadata only and does not run `docker pull`. Then it diffs these paths from that commit to the pushed commit:

- the image's own `dir`
- the shared build-context inputs
- the CI scripts and workflows, `.github/scripts/` and `.github/workflows/`

A change in any of them means rebuild. An image that was never published, or that has no readable label, also gets a rebuild. The check fails closed.

An image with a `base` gets a second check. `build_image.sh` adds the `org.opencontainers.image.base.digest` label to it. That label is the digest of the base image it was built FROM. `changed_images.py` compares that label with the digest that the base's tag points to now. A missing label, an unreadable base digest or a different digest means rebuild. An image with `live: false` skips this check, because a moved base is the cascade it opts out of.

Know these points before you push:

- The diff runs from each image's published revision to the pushed commit. A push of several commits produces **one** build of the final state.
- **A change anywhere under `.github/scripts/` or `.github/workflows/` rebuilds every image of every project**, because the change is in every image's own diff. This includes a change to a *test*, because `test_plan.py` is under `.github/scripts/`. Push CI changes together in one push, not one at a time.
- **Resume is automatic.** After a partial publish, run the workflow again. CI skips the images that published. It rebuilds an image that failed, because its own diff shows the change, or its base digest label names the old base. The revision label alone cannot show the second case: a change under the base's `dir` is not in the dependent image's own diff.
- **The base check compares digests, not commits.** A base rebuilt from the same commit still gets a new digest, because its `created` label changes. If a live image FROM that base did not rebuild in the same run, it rebuilds on the next run.
- **Builds run one at a time.** The build workflow has one concurrency group and does not cancel a running build. A second push waits for the first build to finish.

## How dependencies resolve

Each source of packages has one source of truth. **No file states an R package version.**

- **CRAN**: a dated [Posit Package Manager](https://packagemanager.posit.co) snapshot. The date is in one place only, the `rbase` image **tag**. `build_image.sh` matches a trailing `-YYYY-MM-DD` on the first tag and passes it as `--build-arg CRAN_SNAPSHOT_DATE`. The rule applies to every image. A tag without a date suffix, such as a project's version tag, does not match, and the script passes no build argument.
- **Bioconductor**: the release that pairs with R, from `BiocManager::version()`. The build derives it and no file stores it.
- **GitHub**: a dated CRAN snapshot cannot pin these packages. A project pins each one to a commit SHA in its own file.
- **Resolution**: `pak::pkg_install(refs, dependencies = NA)` installs hard dependencies only (Depends, Imports, LinkingTo), and **excludes Suggests**. There is no hand-computed dependency closure. pak resolves the tree against a snapshot that does not change, so the result is deterministic.

## Project hooks

Two parts of the shared CI respond to files that a project MAY have. A project that does not have them is not affected.

- **`renders`, `chapters` and `groups`.** `plan.py` validates `renders` when a record has one. A record whose `dir` has a `chapters` or `groups` path segment MUST have a `renders` list, and a group's list MUST match the group. No `.qmd` may be claimed by two images.
- **The smoke render.** After `docker build`, in both modes, `build_image.sh` checks for an executable `/usr/local/bin/build_one_chapter.sh` in the image. If it is there, the script renders `/usr/local/lib/ehb/smoke.qmd` with it. A failed render stops the script before any push. An image without that script gets no render, and the log names it.

## Add a project

1. Create `<project>/<version>/` with its Dockerfiles and an `images.yaml`. Use the root `images.yaml` as the model for the fields.
2. Set `base` on the project's lowest image to `rbase` with the current tag from the root `images.yaml`, so it builds FROM `rbase`.
3. Add the new `images.yaml` to every `--images-yaml` argument list. `grep -n -- --images-yaml .github/workflows/*.yml` finds them all. That change is under `.github/workflows/`, so it rebuilds every image of every project.
4. If several images share a `context`, check `SHARED_CONTEXT_INPUTS` in `.github/scripts/changed_images.py`. Only the files named there trigger a rebuild when they change at the context root.
5. Push to `main`, and watch the first build.
6. Check that each new image is public. See "Visibility".
7. Add a project README at `<project>/README.md`, and a row to the "Projects" table above.

## Visibility

**Every published image MUST be public**, so that a consumer needs no `docker login ghcr.io`. Check one with an anonymous read of its manifest, `ghcr_public <image name> <tag>`. It prints `200` when the image is public. Any other code means it is private or does not exist:

```bash
ghcr_public() {
  tok=$(curl -s "https://ghcr.io/token?scope=repository:appliedepi/aedockerpublic/$1:pull" | jq -r .token)
  curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $tok" \
    -H 'Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.v2+json' \
    "https://ghcr.io/v2/appliedepi/aedockerpublic/$1/manifests/$2"
}
```

**You cannot automate a change of GHCR package visibility to public.** There is no REST endpoint and no GraphQL mutation for package visibility. Change it in the web UI, one package at a time:

1. Open the package page.
2. Select the gear icon.
3. Go to Danger Zone, then Change visibility, then Public.
4. Type the package name to confirm.

In the `appliedepi` organization, this step needs an **org admin**. You **cannot reverse** it.

Run the check after the first publish of a **new image name**. If it is private, it stays private until an admin does the steps above.

## Known limitations

- **apt packages do not have individual version pins.** The `ubuntu` base has a digest pin. The packages installed on top of it do not. This is accepted.
- **The build follows a base tag that moved outside CI, and does not check it.** For a base that did not rebuild, the build reads the digest that its published tag points to now. A manual retag or a force-push moves that digest. Every live image FROM that base then rebuilds on the next run, FROM the moved tag. Nothing checks the moved base itself. This is an accepted trust boundary.

---

# Maintaining this repository

This part is for the maintainer of the images. A contributor who uses the images does not need it.

### Design decisions, and why

- **`rbase`, not `base`.** The name leaves room for a separate `pythonbase` later. It also matches the existing `ghcr.io/niphr/cs/rbase`.
- **We own all of `rbase`.** It is `FROM ubuntu` (digest-pinned) plus R from **Posit r-builds**, with **no rocker**. We chose control and consistency over lower maintenance.
- **The image installs the openblas-pthread BLAS on purpose.** It is the BLAS that rocker links, so leaving rocker changed no computed numbers. A different BLAS would change values in many chapters.
- **`GITHUB_PAT` is a BuildKit secret.** Do not use `--build-arg` with `ENV`. That puts the token into the image's `Config.Env`, and `docker inspect` or a push exposes it.

### Traps already found

Use these findings. Do not derive them again.

- **pak leaves gigabytes of build scratch in `/tmp`.** Delete it in the *same* `RUN` layer. If you do not, it stays in the image layer.
- **Docker tag races.** When two builds tag the same image name, the last to finish wins, so a bad build can overwrite a good one. Run builds that share a tag one after the other.

### How we work on this

- **Build on a machine with Docker** before you push. CI rebuilds what changed, so a local build catches a failure first.
- **Check the built image, not only the Dockerfile.** After every build, run `docker inspect <img> --format '{{.Config.Env}}'` to confirm that the image holds no token. A review of the source alone, codex included, does not find a secret in the image.
- **codex is the phase gate.** A phase is done only when codex signs off.
- **The gate is per phase, not per build iteration.** Claude runs the short build loop, and we spend the codex quota with care.
