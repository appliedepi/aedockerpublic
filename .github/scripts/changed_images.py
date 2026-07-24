#!/usr/bin/env python3
"""changed_images.py -- the ONE mechanism that decides which catalog images
have CHANGED, for the CI planner (plan.py) to build+publish.

Rule (owner-designed): an image is rebuilt+republished iff its own files
(its `dir`, the shared build-context inputs, and the .github/ build
machinery) changed since the commit its CURRENTLY-PUBLISHED image was
built from. Never-published, or published with no revision label -> always
CHANGED. This is the single mechanism for both "content changed, rebuild
it" and "a previous run partially failed, resume the missing images" --
the images that published carry the current commit in their
org.opencontainers.image.revision label; the one(s) that failed do not, so
a rerun rebuilds exactly the missing ones. There is no separate per-image
republish guard and no "images.yaml/workflow changed -> rebuild
everything" special case: a .github/ machinery change simply shows up in
EVERY image's own diff (see files_touch_image below), which is what
subsumes that case.

Two steps per catalog image, in this order:
  1. READ the image's published revision: the org.opencontainers.image.
     revision OCI label on $REGISTRY/$REPO/<name>:<first tag>, via a
     METADATA-ONLY registry read (`docker buildx imagetools inspect
     --format ...` fetches the manifest + config, a few KB) -- NEVER
     `docker pull`, which would fetch the full image (these run 3-5GB
     each; a pull per catalog image, every run, would be absurd). Missing
     image, missing label, or any read failure -> None -> CHANGED,
     without needing a git diff at all.
  2. Otherwise, a SINGLE `git diff --name-only <published revision>
     <sha>` -- exactly one diff between two tree snapshots, never a
     per-commit loop, so a push containing several commits (or a
     change-then-revert within the same push) nets to the ACTUAL final
     difference, not one rebuild per intermediate commit. `<sha>` is
     always the caller-supplied --sha (the tip of the current push /
     workflow run), never the bare word "HEAD" -- explicit, so the
     comparison is exactly "published commit -> the commit being built
     now", matching build.yml's own convention of naming both diff
     endpoints explicitly. This is a local repo operation (the checkout
     uses fetch-depth: 0), no network. The resulting file list is then
     matched against THIS image's own dir / shared-context inputs /
     CI machinery (files_touch_image) -- a match -> CHANGED.

This module is the ONLY place in the CI that talks to git or the
registry. plan.py itself stays pure (no subprocess, no network) and only
ever consumes this module's OUTPUT: a list of already-decided CHANGED
image names, fed to it via --changed-image.

Determining the "shared build inputs" for a given image uses the exact
same rule plan.py's build_plan() used to compute inline (before this
split): a file living inside an image's build `context` but outside EVERY
image's own `dir` is a shared input (e.g. epirhandbook/2.7/renv.lock,
COPYed by common AND every chapter Dockerfile, but not itself inside any
chapter's own dir). See files_touch_image below -- kept in exactly one
place so the two modules can never silently drift apart on this rule.

CLI:
    python3 changed_images.py --images-yaml images.yaml \\
        --images-yaml epirhandbook/2.7/images.yaml \\
        --repo appliedepi/aedockerpublic --sha $GITHUB_SHA
Prints one CHANGED image NAME per line to stdout (plan.py's
--changed-image consumes this directly, one flag per line). Per-image
reasoning is printed to stderr for the CI log, never mixed into stdout --
a consumer piping stdout into `--changed-image` args must never have to
filter out log noise.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # noqa: E402 -- reuse matching_dir + load_catalogs; never re-derive them

REVISION_LABEL = "org.opencontainers.image.revision"

# The CI machinery itself: a change here can change how EVERY image is
# built, so it must show up as a match for every image, unconditionally --
# this is what subsumes the old is_special_trigger's "workflow/scripts
# changed -> rebuild everything" case. Deliberately NOT all of `.github/`
# (e.g. CODEOWNERS is excluded) -- same scope the old mechanism used.
MACHINERY_DIRS = (".github/scripts", ".github/workflows")


def is_machinery_file(f):
    return any(plan.matching_dir(f, d) for d in MACHINERY_DIRS)


def files_touch_image(img, changed_files, all_dirs):
    """True iff ANY entry of `changed_files` is one of image `img`'s own
    build inputs. Returns (touched, reason) -- reason is a short
    human-readable string naming the file and the rule that matched, for
    the per-image CI log line.

    Three ways a file can touch an image, checked in this order:
      1. it is under the image's own `dir` (unconditional -- a change
         under an image's own directory always touches it);
      2. it is a SHARED context input: `img`'s build `context` differs
         from its `dir` (true only for the per-chapter split images), the
         file is inside that context, AND the file is outside EVERY
         image's own `dir` in the whole catalog (all_dirs) -- i.e. it is
         a file like renv.lock sitting at the shared context root, not
         some OTHER image's own file (which must not fan out here, or
         per-chapter selectivity would be lost entirely);
      3. it is CI machinery (.github/scripts/, .github/workflows/).
    """
    dir_ = img["dir"]
    ctx = img.get("context", dir_)
    for f in changed_files:
        if plan.matching_dir(f, dir_):
            return True, f"own dir changed: {f}"
        if (
            ctx != dir_
            and plan.matching_dir(f, ctx)
            and not any(plan.matching_dir(f, d) for d in all_dirs)
        ):
            return True, f"shared context input changed: {f}"
        if is_machinery_file(f):
            return True, f"CI machinery changed: {f}"
    return False, "no matching file"


def changed_since(revision, sha, cwd=None):
    """git diff --name-only <revision> <sha> -- repo-relative changed file
    paths. Exactly ONE diff between two tree snapshots (never a per-commit
    loop): a push with several commits, or a change-then-revert within the
    same push, nets to the actual final difference between `revision` and
    `sha`, not one rebuild per intermediate commit. Local, no network (the
    caller's checkout uses fetch-depth: 0).

    Raises RuntimeError if `revision` cannot be diffed (not a valid/
    reachable commit in this checkout) -- the caller decides what that
    means; this function does not guess."""
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


def published_revision(registry, repo, name, tag, timeout=120):
    """The org.opencontainers.image.revision OCI label currently published
    for <name>:<tag>, via a METADATA-ONLY registry read (`docker buildx
    imagetools inspect` fetches the manifest + config -- a few KB -- NEVER
    the image layers; these images run 3-5GB each, so a `docker pull` per
    catalog image, every run, would be absurd).

    Returns the label's string value, or None on ANY of: the image is not
    published, the image has no such label (e.g. built before this label
    existed), the registry read fails, or the response cannot be parsed.
    All of these collapse to the same None -- the caller treats every one
    of them as "never-published = changed", never as a hard error: a
    transient registry hiccup on ONE image must not abort planning every
    other image too."""
    ref = f"{registry}/{repo}/{name}:{tag}"
    try:
        result = subprocess.run(
            [
                "docker", "buildx", "imagetools", "inspect", ref,
                "--format", "{{json .Image.Config.Labels}}",
            ],
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
        labels = json.loads(result.stdout)
    except ValueError:
        print(f"::warning::could not parse imagetools output for {ref}", file=sys.stderr)
        return None
    if not isinstance(labels, dict):
        return None
    return labels.get(REVISION_LABEL)


def image_is_changed(img, registry, repo, sha, all_dirs, diff_cache):
    """(changed: bool, reason: str) for one catalog image. `diff_cache`
    memoizes changed_since() by revision, since several images can share
    the same published revision (e.g. everything published together in
    one prior run)."""
    name = img["name"]
    tag = img["tags"][0]
    revision = published_revision(registry, repo, name, tag)
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
    changed_names = []
    for img in images:
        changed, reason = image_is_changed(
            img, args.registry, args.repo, args.sha, all_dirs, diff_cache
        )
        print(f"{img['name']}: {'CHANGED' if changed else 'unchanged'} -- {reason}",
              file=sys.stderr)
        if changed:
            changed_names.append(img["name"])

    for name in changed_names:
        print(name)


if __name__ == "__main__":
    main()
