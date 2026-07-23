#!/usr/bin/env python3
"""Phase 4 CI planner: images.yaml + a changed-file list -> the ordered set
of images to build.

Pure logic, no GitHub Actions / subprocess dependency, so it is directly
unit-testable (see test_plan.py) -- this is the part of the CI most likely
to be wrong and hardest to observe failing inside an actual Actions run.

Loading images.yaml is a two-stage contract, not a hand-rolled parser: real
PyYAML (`yaml.safe_load`, hash-pinned -- see requirements.txt) does the
parsing, and validate_catalog() below is a strict ALLOWLIST schema over its
output. This replaced a vendored narrow YAML reader (`minimal_yaml.py`,
deleted) that tried to promise "the same meaning as real YAML, or raise" --
an unbounded goal, since YAML's implicit scalar space (dates, hex, booleans,
floats, ...) is larger than any hand-rolled rejection list, and that reader
drew three further rounds of adversarial-review blockers for silently
diverging from real YAML semantics anyway -- four rounds total spent on
this same question (PROJECT.md section 8.9, and 8.4/8.8 for the originals).
The new contract is bounded instead: PyYAML parses, the schema validates
every field against one declared type, and anything else is a hard error --
we never try to out-parse YAML ourselves.

CLI:
    python3 plan.py --images-yaml images.yaml --changed-file a --changed-file b
    python3 plan.py --images-yaml images.yaml --nightly
Prints one JSON object to stdout -- see build_plan()'s docstring for the shape.
"""
import argparse
import json
import re
import sys

import yaml

# Static ceiling matching build.yml/nightly.yml's wired-up jobs
# (build-layer-0 .. build-layer-3, i.e. 4 layers). This is NOT a soft limit:
# a catalog that needs a 5th layer must not be silently truncated -- with
# only 2 images today that would go unnoticed, but Phase 5a adds ~50
# chapter images and a silently-dropped layer there is a silent PARTIAL
# PUBLISH (some images never built, no error). See build_plan()'s check
# below and test_plan.py's test for a catalog deeper than this.
MAX_SUPPORTED_LAYERS = 4


def parse_base(base):
    """'rbase:4.3.2' -> ('rbase', '4.3.2'). None/empty -> ('', '')."""
    if not base:
        return "", ""
    name, _, tag = base.rpartition(":")
    if not name:
        # no ':' present -- treat the whole string as the name, no tag
        return base, ""
    return name, tag


REQUIRED_IMAGE_KEYS = {"name", "dir", "tags", "base", "base_digest"}
# `renders`: for the per-chapter split images (epirhandbook/2.6), the .qmd this
# image renders, repo-relative to the handbook source root. Optional -- rbase
# and the 2.5 monolith render no single file. It states the CONCRETE artifact
# rather than an abstract chapter id, and it carries information `dir` does not:
# `index` renders index.qmd at the source ROOT, not new_pages/index.qmd. Its
# stem is validated against the `dir` basename below, so it cannot drift from
# the build context it belongs to.
# `context`: the docker build CONTEXT, when it differs from `dir`. These are
# two different facts and the split is the first place they diverge:
#   dir     = this image's own files -- the change-detection scope, and where
#             its Dockerfile lives.
#   context = the directory `docker build` is given, i.e. the root that COPY
#             paths resolve against.
# For rbase and the 2.5 monolith they coincide, so `context` is omitted. For a
# 2.6 chapter they cannot: the Dockerfile lives in chapters/<ch>/ but COPYs
# renv.lock and pak_install_subset.R from epirhandbook/2.6/, so the context
# must be 2.6/ while change detection must stay per-chapter. Building with the
# chapter dir as context fails -- the COPY sources are outside it.
OPTIONAL_IMAGE_KEYS = {"live", "frozen", "renders", "context"}
ALLOWED_IMAGE_KEYS = REQUIRED_IMAGE_KEYS | OPTIONAL_IMAGE_KEYS

# Image-name-safe: what is legal in a Docker/GHCR image name component.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
# A single Docker tag: the OCI/Docker rule -- first char [a-zA-Z0-9_], then up
# to 127 of [a-zA-Z0-9_.-]. Crucially this EXCLUDES the comma, the slash, and
# whitespace. The workflow serializes an image's tags with join(',') and
# build_image.sh splits them back on ',', so a tag CONTAINING a comma
# (`"prod,latest"`) would silently become TWO published tags -- a malformed
# field changing the publish decision. Constraining the charset here makes that
# unrepresentable rather than caught downstream.
TAG_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}$")
# A base reference: "<name>:<tag>", both halves non-empty and each side obeying
# its own charset. `base: "rbase:"` (empty tag) previously reached the build
# with an empty base tag; require a real tag after the colon.
BASE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*:[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}$")
# A repo-relative build-context dir, in CANONICAL form: one or more path
# segments of a shell-safe charset, joined by single '/', no leading or
# trailing slash, no empty segment. `dir` is BOTH the Docker build context AND
# the selective-change matcher (matching_dir compares it raw against changed
# file paths), so a non-canonical spelling that validates but doesn't match --
# e.g. `./rbase/4.3.2`, which passes an "is it relative?" check but never
# matches the changed file `rbase/4.3.2/Dockerfile` -- is a SILENT skipped
# rebuild. Requiring the canonical form makes stored dir == what git reports.
# The '.'/'..' segment cases are rejected explicitly below (the charset alone
# would admit them).
DIR_RE = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")
# Exactly "sha256:" + 64 lowercase hex chars. A malformed or truncated
# digest must never look like a valid pin -- build_image.sh trusts this
# field as the base's actual digest pin on the publish path.
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _label(image, index):
    """A human-readable name for error messages: the image's own `name`
    field when it is usable, else its position in the list -- `name` itself
    might be the very thing that's missing or malformed."""
    if isinstance(image, dict) and isinstance(image.get("name"), str) and image["name"]:
        return image["name"]
    return f"images[{index}]"


def validate_catalog(doc, path):
    """Strict ALLOWLIST schema over yaml.safe_load(images.yaml)'s output.
    Rejects anything not explicitly permitted, rather than trying to name
    everything that might be wrong (the blacklist approach minimal_yaml.py
    took, and kept failing at -- see this module's docstring). Every field
    has exactly one declared type; anything else is a hard ValueError
    naming the file, the image, the field, and what was expected. Returns
    the validated `images` list (unchanged) on success -- the same shape
    callers already expect."""
    if not isinstance(doc, dict) or set(doc) != {"images"}:
        raise ValueError(
            f"{path}: top level must be a mapping with exactly one key, "
            f"'images', mapping to a non-empty list; got {doc!r}"
        )

    images = doc["images"]
    if not isinstance(images, list) or not images:
        raise ValueError(f"{path}: 'images' must be a non-empty list; got {images!r}")

    for index, image in enumerate(images):
        _validate_image(image, path, index)

    # Unique image names. Every downstream structure keys by name
    # (by_name = {img["name"]: img ...} in topological_order and build_plan),
    # so a duplicate name silently collapses to the LAST record -- a change
    # under the first would plan the second's dir/tags. Reject it here, where
    # the whole catalog is in view (a per-image check cannot see the clash).
    seen = {}
    for index, image in enumerate(images):
        nm = image["name"]
        if nm in seen:
            raise ValueError(
                f"{path}: duplicate image name {nm!r} (images[{seen[nm]}] and "
                f"images[{index}]). Names must be unique -- every build/publish "
                f"structure keys by name and would silently keep only the last."
            )
        seen[nm] = index

    return images


def _validate_image(image, path, index):
    label = _label(image, index)
    if not isinstance(image, dict):
        raise ValueError(f"{path}: image {label!r} must be a mapping; got {image!r}")

    unknown = set(image) - ALLOWED_IMAGE_KEYS
    if unknown:
        raise ValueError(
            f"{path}: image {label!r} has unknown key(s) {sorted(unknown)} -- "
            f"allowed keys are {sorted(ALLOWED_IMAGE_KEYS)} (a typo, e.g. "
            f"'froze' for 'frozen', lands here)."
        )
    missing = REQUIRED_IMAGE_KEYS - set(image)
    if missing:
        raise ValueError(
            f"{path}: image {label!r} is missing required key(s) {sorted(missing)} "
            f"-- every image needs: {sorted(REQUIRED_IMAGE_KEYS)} (optional: "
            f"{sorted(OPTIONAL_IMAGE_KEYS)})."
        )

    name = image["name"]
    if not isinstance(name, str) or not name or not NAME_RE.match(name):
        raise ValueError(
            f"{path}: image {label!r} field 'name' must be a non-empty string "
            f"matching {NAME_RE.pattern!r} (image-name safe); got {name!r}."
        )

    dir_ = image["dir"]
    if not isinstance(dir_, str) or not dir_:
        raise ValueError(
            f"{path}: image {label!r} field 'dir' must be a non-empty string; got {dir_!r}."
        )
    if not DIR_RE.match(dir_):
        raise ValueError(
            f"{path}: image {label!r} field 'dir'={dir_!r} is not a canonical "
            f"repo-relative path matching {DIR_RE.pattern!r}: no leading './' or "
            f"'/', no trailing slash, no '//', shell-safe segments. It is both the "
            f"build context AND the change matcher, so a non-canonical spelling can "
            f"validate yet never match a changed file -- a silent skipped rebuild."
        )
    if any(seg in (".", "..") for seg in dir_.split("/")):
        raise ValueError(
            f"{path}: image {label!r} field 'dir' must not contain '.' or '..' "
            f"path segments; got {dir_!r}."
        )

    tags = image["tags"]
    if not isinstance(tags, list) or not tags:
        raise ValueError(
            f"{path}: image {label!r} field 'tags' must be a non-empty list; got {tags!r}."
        )
    for j, tag in enumerate(tags):
        # This is what catches PyYAML turning an unquoted 2024-01-01 into a
        # datetime.date, or 0x10 / 2.5 into a number: the schema demands a
        # string, so anything else -- whatever type YAML resolved it to --
        # is rejected here, without plan.py enumerating YAML's implicit-
        # scalar grammar itself.
        if not isinstance(tag, str) or not tag:
            raise ValueError(
                f"{path}: image {label!r} field 'tags'[{j}] must be a non-empty "
                f"string; got {tag!r} ({type(tag).__name__}). If this looks like "
                f"a date/number in images.yaml, quote it so YAML keeps it a string."
            )
        if not TAG_RE.match(tag):
            raise ValueError(
                f"{path}: image {label!r} field 'tags'[{j}]={tag!r} is not a valid "
                f"Docker tag ({TAG_RE.pattern!r}). A comma, slash, or space here is "
                f"especially dangerous: tags are join(',')'d and split(',') back "
                f"downstream, so a comma would silently become two published tags."
            )

    base = image["base"]
    if base is not None and (not isinstance(base, str) or not BASE_RE.match(base)):
        raise ValueError(
            f"{path}: image {label!r} field 'base' must be null or a '<name>:<tag>' "
            f"reference matching {BASE_RE.pattern!r} (both halves non-empty); got "
            f"{base!r}. A bare 'name:' with no tag reaches the build with an empty "
            f"base tag."
        )

    base_digest = image["base_digest"]
    if base_digest is not None and (
        not isinstance(base_digest, str) or not DIGEST_RE.match(base_digest)
    ):
        raise ValueError(
            f"{path}: image {label!r} field 'base_digest' must be null or match "
            f"{DIGEST_RE.pattern!r} exactly; got {base_digest!r}. A malformed or "
            f"truncated digest must never masquerade as a valid pin."
        )
    if base_digest is not None and base is None:
        raise ValueError(
            f"{path}: image {label!r} has base_digest={base_digest!r} but base is "
            f"null -- a digest pin for no base is meaningless and would be silently "
            f"ignored. Remove the base_digest, or give it a base to pin."
        )

    # `source`: the .qmd this image renders. Its STEM must equal the last
    # segment of `dir` -- that directory is this chapter's build context, so if
    # the two disagree the row describes two different chapters and one is
    # wrong. Checking it here is what lets the field be explicit (it names the
    # real artifact) WITHOUT becoming a second thing that can silently drift.
    if "renders" in image:
        renders = image["renders"]
        if not isinstance(renders, str) or not renders.endswith(".qmd"):
            raise ValueError(
                f"{path}: image {label!r} field 'renders' must be a non-empty "
                f"string naming a .qmd file; got {renders!r}."
            )
        dir_basename = image["dir"].rstrip("/").rsplit("/", 1)[-1]
        renders_stem = renders.rsplit("/", 1)[-1][: -len(".qmd")]
        if renders_stem != dir_basename:
            raise ValueError(
                f"{path}: image {label!r} renders {renders!r} (stem "
                f"{renders_stem!r}) but its dir basename is {dir_basename!r} "
                f"({image['dir']!r}). The source is the .qmd this image renders; "
                f"dir is that chapter's build context. They must agree."
            )
        # ...and the NAME must correspond to that same chapter. Checking only
        # source-vs-dir leaves the published artifact name unconstrained: a row
        # could render basics.qmd from chapters/basics while being published as
        # `epirhandbook-cleaning`, passing validation and putting a LYING name
        # on a public registry. The name is the chapter lowercased (Docker
        # requires lowercase; that transform happens only here).
        if not image["name"].endswith(f"-{renders_stem.lower()}"):
            raise ValueError(
                f"{path}: image {label!r} renders {renders!r} but its name does "
                f"not end with '-{renders_stem.lower()}'. The published image name "
                f"must identify the chapter it renders, or the registry artifact "
                f"misrepresents its own content."
            )

    # A per-chapter image MUST declare what it renders. `renders` is optional in
    # general (rbase and the 2.5 monolith render no single file), but a row whose
    # dir sits under a `chapters/` directory is a per-chapter image by
    # construction, and omitting `renders` there would skip the stem/name/dir
    # linkage checks entirely -- the row could then publish under any name.
    if "renders" not in image and "/chapters/" in image["dir"]:
        raise ValueError(
            f"{path}: image {label!r} has dir={image['dir']!r} (a per-chapter "
            f"image) but no 'renders' field. A chapter image must state the .qmd "
            f"it renders, or its name and build context go unchecked."
        )

    # `context`: same canonical-path rules as `dir`, and `dir` MUST live inside
    # it -- the Dockerfile is selected with `-f <dir>/Dockerfile` against this
    # context, so a dir outside the context could not be built.
    if "context" in image:
        context = image["context"]
        if not isinstance(context, str) or not DIR_RE.match(context):
            raise ValueError(
                f"{path}: image {label!r} field 'context'={context!r} is not a "
                f"canonical repo-relative path matching {DIR_RE.pattern!r}."
            )
        if any(seg in (".", "..") for seg in context.split("/")):
            raise ValueError(
                f"{path}: image {label!r} field 'context' must not contain "
                f"'.' or '..' path segments; got {context!r}."
            )
        if not (image["dir"] == context or image["dir"].startswith(context + "/")):
            raise ValueError(
                f"{path}: image {label!r} has dir={image['dir']!r} outside its "
                f"build context {context!r}. The Dockerfile is selected with "
                f"-f <dir>/Dockerfile against that context, so dir must live "
                f"inside it."
            )

    for boolkey in ("live", "frozen"):
        if boolkey in image and not isinstance(image[boolkey], bool):
            raise ValueError(
                f"{path}: image {label!r} field {boolkey!r} must be a real "
                f"boolean (true/false); got {image[boolkey]!r} "
                f"({type(image[boolkey]).__name__}). A quoted \"true\"/\"false\" "
                f"loads as a string, not a boolean -- write it unquoted."
            )


def load_images(images_yaml_path):
    """Read ONE images.yaml -> the validated list[dict] of image records.
    PyYAML parses; validate_catalog() enforces the schema -- see this
    module's docstring for why loading is split this way. No other code
    path in this project reads images.yaml (build_image.sh only ever
    receives already-validated values, as CLI args from this plan)."""
    with open(images_yaml_path) as f:
        doc = yaml.safe_load(f)
    return validate_catalog(doc, images_yaml_path)


def load_catalogs(paths):
    """Merge SEVERAL catalog files into the one logical catalog the planner
    reasons over.

    The catalog is split across files by OWNERSHIP, not by scope: the root
    images.yaml is hand-maintained (rbase, the 2.5 monolith), while
    epirhandbook/2.6/images.yaml is fully GENERATED by that phase's
    generate.py. Keeping them separate means a generated file is never
    hand-edited and a hand-edited file never contains a generated region --
    but the PLANNER must still see one catalog, because base edges cross the
    files: epirhandbook-common (generated, 2.6) is FROM rbase (hand, root).
    Loading only one of them makes `rbase` look like a typo and the plan dies.

    Every image is still defined in exactly ONE file; a name appearing in two
    catalogs is a hard error, the same rule that already forbids a duplicate
    within one file."""
    merged = []
    seen = {}
    for path in paths:
        for image in load_images(path):
            name = image["name"]
            if name in seen:
                raise ValueError(
                    f"{path}: image {name!r} is already defined in {seen[name]!r}. "
                    f"Every image must be defined in exactly one catalog file."
                )
            seen[name] = path
            merged.append(image)
    return merged


def topological_order(images):
    """Kahn's-algorithm layering over the base: edges of the FULL catalog
    (not just a changed subset), so layer order is a fixed property of the
    catalog, independent of which subset a given run happens to touch.

    Returns a list of layers; each layer is a list of image dicts (order
    within a layer is not meaningful -- they have no edges between them).
    Raises ValueError on a cycle, an unknown base name, or more layers than
    the workflow files support (should never happen for a real catalog;
    fail loud rather than silently drop images).
    """
    by_name = {img["name"]: img for img in images}

    # Validate every base reference BEFORE sorting. Without this, an
    # unknown base name (a typo in `base:`) looks IDENTICAL to "this image
    # has no base" to the Kahn's-algorithm loop below: `base_name not in
    # remaining` is true both when the base was already placed in an
    # earlier layer (correct) and when the base was never a real image at
    # all (a typo). That would silently drop the cascade edge -- the image
    # builds as if base-less, and the entire point of `base` (rebuild me
    # when my base rebuilds) silently never fires again. Fail loud instead.
    for name, img in by_name.items():
        base_name, _ = parse_base(img.get("base"))
        if base_name and base_name not in by_name:
            raise ValueError(
                f"image '{name}' has base '{img.get('base')}', but no image named "
                f"'{base_name}' exists in images.yaml (typo?). Known image names: "
                f"{sorted(by_name)}."
            )

    remaining = dict(by_name)
    layers = []
    while remaining:
        # An image is ready once its base (if any) is NOT in `remaining` --
        # i.e. already placed in an earlier layer, or it has no in-catalog base.
        ready = []
        for name, img in remaining.items():
            base_name, _ = parse_base(img.get("base"))
            if not base_name or base_name not in remaining:
                ready.append(name)
        if not ready:
            raise ValueError(f"cycle among: {sorted(remaining)}")
        layers.append([by_name[name] for name in sorted(ready)])
        for name in ready:
            del remaining[name]

    if len(layers) > MAX_SUPPORTED_LAYERS:
        raise ValueError(
            f"catalog requires {len(layers)} layers, but build.yml/nightly.yml only "
            f"wire up build-layer-0..{MAX_SUPPORTED_LAYERS - 1} ({MAX_SUPPORTED_LAYERS} "
            f"layers). Add a build-layer-{MAX_SUPPORTED_LAYERS} job to BOTH workflow "
            f"files (following the existing build-layer-N pattern) and bump "
            f"MAX_SUPPORTED_LAYERS in plan.py before adding a base image this deep -- "
            f"otherwise the deepest images would silently never be planned at all."
        )

    return layers


def matching_dir(changed_file, dir_):
    d = dir_.rstrip("/")
    return changed_file == d or changed_file.startswith(d + "/")


def is_special_trigger(changed_file):
    """A change that must rebuild every live image, regardless of dir
    matching: the catalog itself, any workflow file, or the planner/build
    machinery in .github/scripts/ (a bug there is exactly as dangerous as a
    bug in the workflow YAML, and deserves the same blanket revalidation --
    deliberately broader than the brief's literal "images.yaml or a workflow
    file", for that reason -- see README/plan for the call-out).

    "The catalog" means ANY images.yaml, not just the root one. The catalog is
    split across files by ownership (hand-maintained root + generated per-phase,
    e.g. epirhandbook/2.6/images.yaml), and a row in ANY of them defines what
    exists and how it is built. Matching only the root path meant editing the
    generated split catalog -- which defines 51 of the 53 images -- planned
    NOTHING: the catalog could change what should exist while CI built nothing."""
    return (
        changed_file == "images.yaml"
        or changed_file.endswith("/images.yaml")
        or changed_file.startswith(".github/workflows/")
        or changed_file.startswith(".github/scripts/")
    )


def build_plan(images, changed_files=None, nightly=False):
    """Returns:
      {
        "layers": [ [image_record, ...], ... ],  # dependency order, base-most first
        "num_layers": int,
        "image_names": [str, ...],               # flat, in layer order
        "trigger": "nightly" | "special" | "selective" | "none",
      }
    Each image_record is the image's images.yaml dict PLUS:
      base_name, base_tag    -- parsed from `base`
      base_freshly_built     -- true iff base_name is ALSO in this plan (i.e.
                                 being built in an earlier layer of this SAME
                                 run). true means "re-resolve the digest live
                                 from the registry after the base's push";
                                 false means "use base_digest as recorded in
                                 images.yaml" -- this is the digest-pinning
                                 chicken-and-egg resolution (see images.yaml).
      frozen                 -- normalized bool (defaults False), passed
                                 through so build_image.sh can refuse to
                                 republish over an already-published frozen
                                 tag (see images.yaml's `frozen:` field).
    """
    all_layers = topological_order(images)
    by_name = {img["name"]: img for img in images}

    if nightly:
        trigger = "nightly"
        selected = {name for name, img in by_name.items() if img.get("live", True)}
    else:
        changed_files = changed_files or []
        if any(is_special_trigger(f) for f in changed_files):
            trigger = "special"
            selected = {name for name, img in by_name.items() if img.get("live", True)}
        else:
            # Files that live in a build CONTEXT but inside no image's own dir
            # are SHARED build inputs: epirhandbook/2.6/renv.lock and
            # pak_install_subset.R sit at the 2.6 context root and are COPYed by
            # common AND every chapter Dockerfile. Matching `dir` alone missed
            # them entirely -- editing the installer or the lockfile copy planned
            # NOTHING, while actually changing every image built from that
            # context. A file that IS under some image's dir is that image's own
            # file, so it must not fan out to the whole context (that would
            # destroy per-chapter selectivity).
            all_dirs = [img["dir"] for img in images if img.get("dir")]

            def is_shared_context_input(f):
                return not any(matching_dir(f, d) for d in all_dirs)

            direct = set()
            for f in changed_files:
                for img in images:
                    ctx = img.get("context")
                    if (
                        ctx
                        and ctx != img.get("dir")
                        and matching_dir(f, ctx)
                        and is_shared_context_input(f)
                    ):
                        direct.add(img["name"])
                        continue
                    if img.get("dir") and matching_dir(f, img["dir"]):
                        direct.add(img["name"])

            # Cascade: transitively add anyone whose base (direct or
            # already-cascaded) is in the selected set -- but ONLY if that
            # dependent image is live. A cascade is an AUTOMATIC rebuild
            # triggered by the base moving, which is exactly the class of
            # automatic rebuild `live: false` opts out of. A DIRECT edit to
            # a frozen image's own files still builds it (that is an
            # intentional, explicit change, not an automatic one) --
            # `direct` above is never filtered by `live` for that reason.
            selected = set(direct)
            changed_this_pass = True
            while changed_this_pass:
                changed_this_pass = False
                for img in images:
                    name = img["name"]
                    if name in selected:
                        continue
                    if not img.get("live", True):
                        continue
                    base_name, _ = parse_base(img.get("base"))
                    if base_name and base_name in selected:
                        selected.add(name)
                        changed_this_pass = True

            trigger = "selective" if selected else "none"

    layers_out = []
    for layer in all_layers:
        layer_out = []
        for img in layer:
            if img["name"] not in selected:
                continue
            base_name, base_tag = parse_base(img.get("base"))
            rec = dict(img)
            rec["base_name"] = base_name
            rec["base_tag"] = base_tag
            rec["base_freshly_built"] = bool(base_name) and base_name in selected
            # Normalized (defaults to False for a catalog entry that omits
            # the field) so build_image.sh always receives an explicit
            # true/false rather than having to special-case "missing".
            rec["frozen"] = bool(img.get("frozen", False))
            # Normalized so the build step never has to decide: the docker
            # build context, defaulting to `dir` when the catalog omits it
            # (rbase, the 2.5 monolith). The 2.6 split images set it, because
            # their Dockerfile's COPY paths resolve against epirhandbook/2.6,
            # not against the chapter directory the Dockerfile sits in.
            rec["context"] = img.get("context", img["dir"])
            layer_out.append(rec)
        if layer_out:
            layers_out.append(layer_out)

    image_names = [img["name"] for layer in layers_out for img in layer]

    return {
        "layers": layers_out,
        "num_layers": len(layers_out),
        "image_names": image_names,
        "trigger": trigger,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    # Repeatable: the catalog is split across files by ownership (hand-
    # maintained root vs generated per-phase), but base edges cross them, so
    # the planner must be given every file that makes up the one logical
    # catalog. See load_catalogs.
    ap.add_argument("--images-yaml", required=True, action="append",
                    dest="images_yaml_paths",
                    help="catalog file; repeat for each file in the catalog")
    ap.add_argument("--changed-file", action="append", default=[], dest="changed_files")
    ap.add_argument("--nightly", action="store_true")
    # For shell consumers (build/render loops): print "chapter<TAB>image:tag"
    # for every row that names a chapter. This is how a script learns which
    # image renders which chapter -- it must NEVER reconstruct
    # "epirhandbook-<chapter>:<tag>" itself, or the naming rule ends up living
    # in the catalog AND in every consumer, which is the duplication the
    # single-source catalog exists to prevent.
    ap.add_argument("--chapter-images", action="store_true",
                    help="print 'chapter<TAB>image:tag' per chapter row and exit")
    args = ap.parse_args()

    images = load_catalogs(args.images_yaml_paths)

    if args.chapter_images:
        for img in images:
            if not img.get("renders"):
                continue          # the common base renders no single .qmd
            # The chapter id is the dir basename -- validate_catalog has already
            # proven it equals the source's stem, so either is authoritative.
            chapter = img["dir"].rstrip("/").rsplit("/", 1)[-1]
            print(f"{chapter}\t{img['name']}:{img['tags'][0]}\t{img['renders']}")
        return

    result = build_plan(images, changed_files=args.changed_files, nightly=args.nightly)
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
