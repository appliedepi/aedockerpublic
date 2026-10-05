#!/usr/bin/env python3
"""changed_images.py: the one mechanism that decides which catalog images
changed, so that the CI planner (plan.py) builds and publishes them.

The rule, set by the owner: CI rebuilds and republishes an image if and only if
one of these holds:
  - its own files changed since the commit of its published image. Its own
    files are its `dir`, the shared build-context inputs and the .github/
    build machinery.
  - it was not built FROM the published digest of its base.
An image that was never published, or has no revision label, is always
changed. There is no separate per-image republish guard. There is also no
special case of "images.yaml or a workflow changed, so rebuild everything".
A change to the .github/ machinery shows in the diff of every image (see
files_touch_image below), and that covers the case.

The base check lets a rerun complete a partial publish. An image that failed
to publish keeps its old revision label. Its own diff since then can be
empty, because a change under its base's dir is not one of its own files.
Only the base-digest label shows that it was built FROM an old base (see
base_is_changed below).

Three steps for each catalog image, in this order:
  1. Read the image's published revision. That is the
     org.opencontainers.image.revision OCI label on
     $REGISTRY/$REPO/<name>:<first tag>. The read is metadata-only:
     `docker buildx imagetools inspect --format ...` fetches the manifest and
     config, a few KB. It never runs `docker pull`, which would fetch the
     full image. These images are 3-5GB each, and CI would pull each one on
     every run. A missing image, a missing label or any read failure gives
     None, and the image is changed with no git diff.
  2. Otherwise, run one `git diff --name-only <published revision> <sha>`.
     This is one diff between two tree snapshots, never a loop over commits.
     So a push with several commits, or a change and its revert in one push,
     gives only the final difference. It does not give one rebuild per
     intermediate commit. `<sha>` is always the --sha from the caller (the
     tip of the current push or workflow run), never "HEAD". So the diff
     always runs from the published commit to the commit being built now.
     build.yml also names both diff endpoints. The diff is local, with no
     network, because the checkout uses fetch-depth: 0. files_touch_image
     then matches the file list against this image's own dir, the shared
     context inputs and the CI machinery. A match means changed.
  3. For an image with a base, compare two digests. One is its
     org.opencontainers.image.base.digest label, which build_image.sh
     stamps. The other is the digest its base's tag points to now, from a
     second metadata-only read. A missing label, an unreadable digest or a
     difference means changed. An image with `live: false` skips this step.

This module is the only part of the build plan that uses git or the
registry. build_image.sh also reads the registry, to resolve the digest of
an image's base, but it does not decide what to build. plan.py stays pure,
with no subprocess and no network. It only reads this module's output: a
list of image names already decided as changed, passed with --changed-image.

The rule for the "shared build inputs" of an image is the rule that plan.py's
build_plan() used inline before this split. A file inside an image's build
`context` but outside the `dir` of every image is a shared input. One example
is epirhandbook/2.9/pak_install_subset.R. All eight Dockerfiles under
epirhandbook/2.9/ COPY it, but it is not inside the dir of any image. The
rule lives only in files_touch_image (below), so the two modules cannot
disagree on it.

CLI:
    python3 changed_images.py --images-yaml images.yaml \\
        --images-yaml epirhandbook/2.9/images.yaml \\
        --repo appliedepi/aedockerpublic --sha $GITHUB_SHA
It prints one changed image name per line to stdout. plan.py's
--changed-image reads this directly, one flag per line. The reason for each
image goes to stderr for the CI log, never to stdout. A consumer that pipes
stdout into `--changed-image` args then has no log lines to filter out.
"""
import argparse
import functools
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # noqa: E402 -- reuse matching_dir + load_catalogs; never re-derive them

REVISION_LABEL = "org.opencontainers.image.revision"
# build_image.sh stamps this on every image that has a base: the digest of
# the exact base image it was built FROM. See base_is_changed below.
BASE_DIGEST_LABEL = "org.opencontainers.image.base.digest"

# The CI machinery. A change here can change how every image is built, so it
# matches every image with no condition. This replaces the "workflow/scripts
# changed -> rebuild everything" case of the old is_special_trigger. It is
# not all of `.github/`: for example, CODEOWNERS is excluded. That is the
# scope the old mechanism used.
MACHINERY_DIRS = (".github/scripts", ".github/workflows")


def is_machinery_file(f):
    return any(plan.matching_dir(f, d) for d in MACHINERY_DIRS)


# The files at the root of a shared build context that are build inputs.
# This is an allowlist, not a denylist of documentation. A denylist must be
# right about every file that can appear. For example, a suffix rule that
# excludes ".md" stops rebuilding an image when someone writes `COPY . /src`
# or `ADD notes.md`. The image then goes stale with no sign. An allowlist
# fails the other way: a real input that is not listed here does not trigger
# a rebuild. test_every_copied_context_file_is_a_declared_input finds that
# case, because it parses what the Dockerfiles COPY.
#
# The reason for the list: epirhandbook/2.7 was the shared context for common
# and all 49 chapters. Its root held these inputs beside a README, the change
# notes, a patch and five measurement TSVs. The rule "anything in the context
# outside an image's own dir" matched all of those, so a README edit rebuilt
# 50 of 51 images.
#
# 2.9 keeps that shape. epirhandbook/2.9 is the shared context for
# epirhandbook-common, the six group images and the monolith. Its root holds
# a README beside these inputs. The same broad rule would rebuild eight of
# the merged catalog's nine images on one README edit.
#
# Paths are relative to the context directory.
SHARED_CONTEXT_INPUTS = (
    "images.yaml",
    "pak_install_subset.R",
    "packages_github.json",
)


def is_shared_context_input(f, ctx):
    """True iff `f` is one of the declared build inputs at `ctx`'s root."""
    prefix = ctx.rstrip("/") + "/"
    if not f.startswith(prefix):
        return False
    return f[len(prefix):] in SHARED_CONTEXT_INPUTS


def files_touch_image(img, changed_files, all_dirs):
    """True iff any entry of `changed_files` is one of the build inputs of
    image `img`. Returns (touched, reason). `reason` is a short string for
    the per-image CI log line. It names the file and the rule that matched.

    A file touches an image in three ways, checked in this order:
      1. It is under the image's own `dir`. Such a file always touches the
         image.
      2. It is a shared context input. Three conditions MUST all hold:
         - `img`'s build `context` differs from its `dir`. That is true for
           all eight images in epirhandbook/2.9/images.yaml, and for no
           other.
         - The file is one of the declared inputs at that context's root
           (see SHARED_CONTEXT_INPUTS).
         - The file is outside the own `dir` of every image in the whole
           catalog (all_dirs).
         So pak_install_subset.R touches every image that shares the
         context. A file in the dir of another image does not, which keeps
         the selection per image. A README beside the inputs does not.
      3. It is CI machinery (.github/scripts/, .github/workflows/).
    """
    dir_ = img["dir"]
    ctx = img.get("context", dir_)
    for f in changed_files:
        if plan.matching_dir(f, dir_):
            return True, f"own dir changed: {f}"
        if (
            ctx != dir_
            and is_shared_context_input(f, ctx)
            and not any(plan.matching_dir(f, d) for d in all_dirs)
        ):
            return True, f"shared context input changed: {f}"
        if is_machinery_file(f):
            return True, f"CI machinery changed: {f}"
    return False, "no matching file"


def changed_since(revision, sha, cwd=None):
    """The changed file paths, relative to the repo, from
    `git diff --name-only <revision> <sha>`. It runs one diff between two
    tree snapshots, never a loop over commits. So a push with several
    commits, or a change and its revert in one push, gives only the final
    difference between `revision` and `sha`. It does not give one rebuild
    per intermediate commit. The diff is local, with no network, because
    the caller's checkout uses fetch-depth: 0.

    Raises RuntimeError if `revision` cannot be diffed, because it is not a
    valid or reachable commit in this checkout. The caller decides what
    that means."""
    result = subprocess.run(
        ["git", "diff", "--name-only", revision, sha],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git diff --name-only {revision} {sha} failed (exit "
            f"{result.returncode}): {result.stderr.strip()}"
        )
    return [line for line in result.stdout.splitlines() if line]


def _imagetools_inspect(ref, fmt, timeout):
    """Parsed JSON of `docker buildx imagetools inspect <ref> --format <fmt>`.
    This is a metadata-only registry read: the manifest and config, a few KB,
    never the image layers. These images are 3-5GB each, so CI must not run
    a `docker pull` for each catalog image on every run.

    Returns None in each of these cases:
      - the image is not published
      - the registry read fails
      - the response cannot be parsed
    None is never a hard error. A short registry fault on one image MUST NOT
    stop the plan for all the other images."""
    try:
        result = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", ref, "--format", fmt],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"::warning::could not inspect {ref}: {e}", file=sys.stderr)
        return None
    if result.returncode != 0:
        print(
            f"::notice::{ref} not found or not inspectable "
            f"(exit {result.returncode}): {result.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        print(f"::warning::could not parse imagetools output for {ref}", file=sys.stderr)
        return None


def published_labels(registry, repo, name, tag, timeout=120):
    """The OCI labels currently published on <name>:<tag>, as a dict, or
    None when they cannot be read (see _imagetools_inspect)."""
    ref = f"{registry}/{repo}/{name}:{tag}"
    labels = _imagetools_inspect(ref, "{{json .Image.Config.Labels}}", timeout)
    return labels if isinstance(labels, dict) else None


def published_revision(registry, repo, name, tag, labels_of=published_labels):
    """The REVISION_LABEL value published on <name>:<tag>, or None when the
    image is not published, has no such label, or cannot be read. The caller
    reads each of these cases as "never published, so changed"."""
    return (labels_of(registry, repo, name, tag) or {}).get(REVISION_LABEL)


def published_digest(registry, repo, name, tag, timeout=120):
    """The manifest digest ("sha256:...") that <name>:<tag> currently
    points to, or None when it cannot be read. This is the same digest
    build_image.sh takes from the `Digest:` line of imagetools inspect when
    it resolves a base, and stamps as BASE_DIGEST_LABEL. Use
    `{{json .Manifest}}`, not `{{.Manifest.Digest}}`: buildx 0.11.2 ignores
    the second and prints its default text."""
    ref = f"{registry}/{repo}/{name}:{tag}"
    manifest = _imagetools_inspect(ref, "{{json .Manifest}}", timeout)
    if not isinstance(manifest, dict):
        return None
    digest = manifest.get("digest")
    if isinstance(digest, str) and digest.startswith("sha256:"):
        return digest
    return None


def base_is_changed(img, registry, repo, labels_of, digest_of):
    """(changed: bool, reason: str) for the image's BASE. True when the image
    has a base in this catalog and its BASE_DIGEST_LABEL is missing, the
    base's published digest cannot be read, or the two differ.

    This is the cross-run half of the cascade in plan.build_plan. A base
    rebuilt in this run already cascades there. A base published in an
    earlier run does not, and the image's own diff cannot see it, because
    files_touch_image never looks at the base's dir. Two cases need this
    check:
      - A partial publish leaves a dependent on the old base, and a rerun
        finds both "unchanged".
      - A base republished at the same source revision gets a new digest,
        because the created label changes and the rbase date tag is
        mutable. No commit comparison can see that.

    An image with `live: false` is skipped. A rebuild because the base moved
    is one of the automatic rebuilds that `live: false` turns off."""
    base_name, base_tag = plan.parse_base(img.get("base"))
    if not base_name or not img.get("live", True):
        return False, "no base, or not live"
    base = f"{base_name}:{base_tag}"
    labels = labels_of(registry, repo, img["name"], img["tags"][0]) or {}
    built_from = labels.get(BASE_DIGEST_LABEL)
    if not built_from:
        return True, f"no {BASE_DIGEST_LABEL} label, so the {base} it was built FROM is unknown"
    current = digest_of(registry, repo, base_name, base_tag)
    if not current:
        return True, f"the published digest of base {base} could not be read"
    if built_from != current:
        return True, f"built FROM base {base} at {built_from}, now published at {current}"
    return False, f"built FROM the current published base {base} ({current})"


def image_is_changed(img, registry, repo, sha, all_dirs, diff_cache,
                     revision_of=published_revision, labels_of=published_labels,
                     digest_of=published_digest):
    """(changed: bool, reason: str) for one catalog image. `diff_cache`
    memoizes changed_since() by revision, because several images can share
    one published revision, for example all images published in one earlier
    run.

    `revision_of`, `labels_of` and `digest_of` are the three registry reads,
    each with the signature (registry, repo, name, tag) and the result of
    published_revision, published_labels and published_digest. Tests pass
    dicts behind them, so no test needs the network."""
    name = img["name"]
    tag = img["tags"][0]
    revision = revision_of(registry, repo, name, tag)
    if not revision:
        return True, "not published, or no revision label (never-published = changed)"

    if revision not in diff_cache:
        try:
            diff_cache[revision] = changed_since(revision, sha)
        except RuntimeError as e:
            print(
                f"::warning::{name}: {e}; treating as CHANGED "
                f"(fail toward rebuilding rather than silently skipping).",
                file=sys.stderr,
            )
            diff_cache[revision] = None  # sentinel: unresolvable

    changed_files = diff_cache[revision]
    if changed_files is None:
        return True, f"published revision {revision} could not be diffed"

    touched, reason = files_touch_image(img, changed_files, all_dirs)
    if touched:
        return True, f"{reason} (since published revision {revision})"
    base_changed, base_reason = base_is_changed(img, registry, repo, labels_of, digest_of)
    if base_changed:
        return True, base_reason
    return False, f"unchanged since published revision {revision}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--images-yaml", required=True, action="append",
                    dest="images_yaml_paths",
                    help="catalog file; repeat for each file in the catalog")
    ap.add_argument("--repo", required=True,
                    help="lowercased owner/repo, e.g. appliedepi/aedockerpublic")
    ap.add_argument("--sha", required=True,
                    help="the commit being built (github.sha) -- the upper "
                         "diff endpoint for every image")
    ap.add_argument("--registry", default="ghcr.io")
    args = ap.parse_args()

    images = plan.load_catalogs(args.images_yaml_paths)
    all_dirs = [img["dir"] for img in images if img.get("dir")]

    diff_cache = {}
    # Read the labels of each image once: the revision and the base-digest
    # label come from the same read. All the group images have the same base.
    # Read each base digest once, so all of them compare against one value.
    labels_of = functools.lru_cache(maxsize=None)(published_labels)
    digest_of = functools.lru_cache(maxsize=None)(published_digest)

    def revision_of(registry, repo, name, tag):
        return published_revision(registry, repo, name, tag, labels_of=labels_of)

    changed_names = []
    for img in images:
        changed, reason = image_is_changed(
            img, args.registry, args.repo, args.sha, all_dirs, diff_cache,
            revision_of=revision_of, labels_of=labels_of, digest_of=digest_of,
        )
        print(f"{img['name']}: {'CHANGED' if changed else 'unchanged'} -- {reason}",
              file=sys.stderr)
        if changed:
            changed_names.append(img["name"])

    for name in changed_names:
        print(name)


if __name__ == "__main__":
    main()
