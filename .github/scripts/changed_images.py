#!/usr/bin/env python3
"""changed_images.py -- the ONE mechanism that decides which catalog images
have CHANGED, for the CI planner (plan.py) to build+publish.

Rule (owner-designed): an image is rebuilt+republished iff its own files
(its `dir`, the shared build-context inputs, and the .github/ build
machinery) changed since the commit its CURRENTLY-PUBLISHED image was
built from, or it was not built FROM the currently published digest of its
base. Never-published, or published with no revision label -> always
CHANGED. There is no separate per-image republish guard and no
"images.yaml/workflow changed -> rebuild everything" special case: a
.github/ machinery change simply shows up in EVERY image's own diff (see
files_touch_image below), which is what subsumes that case.

The base check is what makes a rerun after a partial publish complete. An
image that failed to publish keeps its old revision label, and its own
diff since then can be empty: a change under its base's dir is not one of
its own files. Only the base-digest label shows that it was built FROM an
old base (see base_is_changed below).

Three steps per catalog image, in this order:
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
  3. For an image with a base: compare its
     org.opencontainers.image.base.digest label (stamped by
     build_image.sh) with the digest its base's tag points to now, by a
     second metadata-only read. A missing label, an unreadable digest or a
     difference -> CHANGED. An image with `live: false` skips this step.

This module is the only part of the build plan that talks to git or the
registry. build_image.sh also reads the registry, to resolve the digest of
an image's base, but it does not decide what to build. plan.py
stays pure (no subprocess, no network) and only consumes this module's
OUTPUT: a list of already-decided CHANGED image names, passed to it with
--changed-image.

Determining the "shared build inputs" for a given image uses the exact
same rule plan.py's build_plan() used to compute inline (before this
split): a file living inside an image's build `context` but outside EVERY
image's own `dir` is a shared input. One example is
epirhandbook/2.9/pak_install_subset.R, COPYed by all eight Dockerfiles under
epirhandbook/2.9/, but not itself inside any image's own dir. See
files_touch_image below -- kept in exactly one place so the two modules can
never silently drift apart on this rule.

CLI:
    python3 changed_images.py --images-yaml images.yaml \\
        --images-yaml epirhandbook/2.9/images.yaml \\
        --repo appliedepi/aedockerpublic --sha $GITHUB_SHA
Prints one CHANGED image NAME per line to stdout (plan.py's
--changed-image consumes this directly, one flag per line). Per-image
reasoning is printed to stderr for the CI log, never mixed into stdout --
a consumer piping stdout into `--changed-image` args must never have to
filter out log noise.
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

# The CI machinery itself: a change here can change how EVERY image is
# built, so it must show up as a match for every image, unconditionally --
# this is what subsumes the old is_special_trigger's "workflow/scripts
# changed -> rebuild everything" case. Deliberately NOT all of `.github/`
# (e.g. CODEOWNERS is excluded) -- same scope the old mechanism used.
MACHINERY_DIRS = (".github/scripts", ".github/workflows")


def is_machinery_file(f):
    return any(plan.matching_dir(f, d) for d in MACHINERY_DIRS)


# The files at a shared build context's root that are genuinely build inputs.
# An ALLOWLIST, not a denylist of documentation, because a denylist has to be
# right about every file that might ever appear: a suffix rule that excludes
# ".md" quietly stops rebuilding an image the day someone writes
# `COPY . /src` or `ADD notes.md`, and the image goes stale with nothing to
# show for it. Naming the inputs instead fails the other way -- add a real
# input and forget to list it here, and it simply does not trigger, which
# test_every_copied_context_file_is_a_declared_input catches by parsing what
# the Dockerfiles actually COPY.
#
# Why this exists: epirhandbook/2.7 was the shared context for common and all
# 49 chapters. Its root held these inputs beside a README, the change notes,
# a patch and five measurement TSVs. Matching "anything in the context
# outside an image's own dir" swept all of those in, so a README edit rebuilt
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
    """True iff ANY entry of `changed_files` is one of image `img`'s own
    build inputs. Returns (touched, reason) -- reason is a short
    human-readable string naming the file and the rule that matched, for
    the per-image CI log line.

    Three ways a file can touch an image, checked in this order:
      1. it is under the image's own `dir` (unconditional -- a change
         under an image's own directory always touches it);
      2. it is a SHARED context input: `img`'s build `context` differs
         from its `dir` (true for all eight images in
         epirhandbook/2.9/images.yaml, and for no other), the
         file is one of the DECLARED inputs at that context's root (see
         SHARED_CONTEXT_INPUTS), AND it is outside EVERY image's own `dir`
         in the whole catalog (all_dirs) -- so pak_install_subset.R fans
         out to every image sharing the context, while some OTHER image's
         own file does not (which would lose per-image selectivity) and
         neither does a README sitting beside it;
      3. it is CI machinery (.github/scripts/, .github/workflows/).
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


def _imagetools_inspect(ref, fmt, timeout):
    """Parsed JSON of `docker buildx imagetools inspect <ref> --format <fmt>`,
    a METADATA-ONLY registry read (the manifest + config, a few KB, NEVER
    the image layers; these images run 3-5GB each, so a `docker pull` per
    catalog image, every run, would be absurd).

    Returns None on ANY of: the image is not published, the registry read
    fails, or the response cannot be parsed. All of these collapse to the
    same None, never a hard error: a transient registry hiccup on ONE image
    must not abort planning every other image too."""
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
    image is not published, has no such label, or cannot be read. Every one
    of these means "never-published = changed" to the caller."""
    return (labels_of(registry, repo, name, tag) or {}).get(REVISION_LABEL)


def published_digest(registry, repo, name, tag, timeout=120):
    """The manifest digest ("sha256:...") that <name>:<tag> currently
    points to, or None when it cannot be read. This is the same digest
    build_image.sh takes from the `Digest:` line of imagetools inspect when
    it resolves a base, and stamps as BASE_DIGEST_LABEL. `{{json .Manifest}}`
    and not `{{.Manifest.Digest}}`: buildx 0.11.2 ignores the second and
    prints its default text."""
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

    This is the cross-run half of plan.build_plan's cascade. A base rebuilt
    in THIS run already cascades there. A base published in an EARLIER run
    does not, and the image's own diff cannot see it: files_touch_image
    never looks at the base's dir. Two cases need it. A partial publish
    leaves a dependent on the old base, and a rerun finds both "unchanged".
    A base republished at the SAME source revision gets a new digest (the
    created label changes, and the rbase date tag is mutable), which no
    commit comparison can see.

    An image with `live: false` is skipped. A base that moved is exactly
    the automatic rebuild that `live: false` opts out of."""
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
    memoizes changed_since() by revision, since several images can share
    the same published revision (e.g. everything published together in
    one prior run).

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
    # Read each image's labels once: the revision and the base-digest label
    # come from the same read. Every group image reads the same base: read
    # each base digest once, so all of them compare against one value.
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
