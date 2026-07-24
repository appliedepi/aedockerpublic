#!/usr/bin/env python3
"""CI planner: images.yaml + a list of already-CHANGED image names -> the
ordered set of images to build.

Pure logic, no GitHub Actions / subprocess / registry / git dependency, so
it is directly unit-testable (see test_plan.py) -- this is the part of the
CI most likely to be wrong and hardest to observe failing inside an actual
Actions run. Deciding WHICH images changed is a separate, impure concern
(it needs git and the registry) that lives entirely in the sibling
`changed_images.py` -- this module only ever consumes that decision's
OUTPUT (a list of image names), never recomputes it and never talks to
git or the registry itself.

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
    python3 plan.py --images-yaml images.yaml --changed-image name-a --changed-image name-b
Prints one JSON object to stdout -- see build_plan()'s docstring for the shape.
"""
import argparse
import json
import re
import sys

import yaml

# Static ceiling matching build.yml's wired-up jobs
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


REQUIRED_IMAGE_KEYS = {"name", "dir", "tags", "base"}
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
OPTIONAL_IMAGE_KEYS = {"live", "renders", "context"}
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
            f"'liev' for 'live', lands here)."
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

    # `source`: the .qmd this image renders. Its STEM must equal the last
    # segment of `dir` -- that directory is this chapter's build context, so if
    # the two disagree the row describes two different chapters and one is
    # wrong. Checking it here is what lets the field be explicit (it names the
    # real artifact) WITHOUT becoming a second thing that can silently drift.
    if "renders" in image:
        renders = image["renders"]
        if isinstance(renders, list):
            if not renders:
                raise ValueError(
                    f"{path}: image {label!r} field 'renders' must be a "
                    f"non-empty list when given as a list; got {renders!r}."
                )
            seen_qmd = set()
            for j, r in enumerate(renders):
                if not isinstance(r, str) or not r or not r.endswith(".qmd"):
                    raise ValueError(
                        f"{path}: image {label!r} field 'renders'[{j}] must "
                        f"be a non-empty string naming a .qmd file; got "
                        f"{r!r}."
                    )
                if r in seen_qmd:
                    raise ValueError(
                        f"{path}: image {label!r} field 'renders' lists "
                        f"{r!r} more than once. Each .qmd may appear at "
                        f"most once per image -- listing it twice does not "
                        f"say which build owns rendering it."
                    )
                seen_qmd.add(r)
            # The NAME must identify the GROUP this record renders (its dir
            # basename, lowercased) -- the list-form counterpart of the
            # string-form chapter check below. A row could otherwise render
            # {regression,stat_tests}.qmd from groups/analysis while being
            # published as `epirhandbook-wrong-group`, passing validation
            # and putting a LYING name on a public registry.
            dir_basename = image["dir"].rstrip("/").rsplit("/", 1)[-1]
            if not image["name"].endswith(f"-{dir_basename.lower()}"):
                raise ValueError(
                    f"{path}: image {label!r} renders a list of .qmd files "
                    f"under dir {image['dir']!r} but its name does not end "
                    f"with '-{dir_basename.lower()}'. The published image "
                    f"name must identify the group it renders, or the "
                    f"registry artifact misrepresents its own content."
                )
        else:
            if not isinstance(renders, str) or not renders.endswith(".qmd"):
                raise ValueError(
                    f"{path}: image {label!r} field 'renders' must be a "
                    f"non-empty string naming a .qmd file, or a non-empty "
                    f"list of such strings; got {renders!r}."
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

    # A per-chapter or per-group image MUST declare what it renders. `renders`
    # is optional in general (rbase and the 2.5 monolith render no single
    # file), but a row whose dir has a `chapters` or `groups` path segment is
    # a per-chapter or per-group image by construction, and omitting
    # `renders` there would skip the stem/name/dir linkage checks entirely --
    # the row could then publish under any name. Matched by SEGMENT (split
    # dir on '/'), not substring: a substring match on '/chapters/' or
    # '/groups/' would miss a dir that IS exactly "chapters" or "groups", or
    # one where the segment is the first component (no leading '/').
    dir_segments = image["dir"].split("/")
    if "renders" not in image and (
        "chapters" in dir_segments or "groups" in dir_segments
    ):
        raise ValueError(
            f"{path}: image {label!r} has dir={image['dir']!r} (a per-chapter "
            f"or per-group image -- its dir has a 'chapters' or 'groups' path "
            f"segment) but no 'renders' field. Such an image must state the "
            f".qmd file(s) it renders, or its name and build context go "
            f"unchecked."
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

    if "live" in image and not isinstance(image["live"], bool):
        raise ValueError(
            f"{path}: image {label!r} field 'live' must be a real "
            f"boolean (true/false); got {image['live']!r} "
            f"({type(image['live']).__name__}). A quoted \"true\"/\"false\" "
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
    seen_renders = {}
    for path in paths:
        for image in load_images(path):
            name = image["name"]
            if name in seen:
                raise ValueError(
                    f"{path}: image {name!r} is already defined in {seen[name]!r}. "
                    f"Every image must be defined in exactly one catalog file."
                )
            seen[name] = path
            # No .qmd may be rendered by more than one image, across the
            # WHOLE combined catalog (every --images-yaml file together, not
            # per file) -- two images racing to publish the same page under
            # two different names would each look correct on its own.
            # Compared as raw strings exactly as written in `renders`, the
            # same convention validate_catalog already uses elsewhere --
            # `renders` has no canonical-form rule.
            renders = image.get("renders")
            if renders is not None:
                qmds = [renders] if isinstance(renders, str) else renders
                for qmd in qmds:
                    if qmd in seen_renders:
                        raise ValueError(
                            f"{path}: image {name!r} field 'renders' names "
                            f"{qmd!r}, which is already rendered by image "
                            f"{seen_renders[qmd]!r}. Every .qmd may be "
                            f"rendered by exactly one image."
                        )
                    seen_renders[qmd] = name
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
            f"catalog requires {len(layers)} layers, but build.yml only wires "
            f"up build-layer-0..{MAX_SUPPORTED_LAYERS - 1} ({MAX_SUPPORTED_LAYERS} "
            f"layers). Add a build-layer-{MAX_SUPPORTED_LAYERS} job to build.yml "
            f"(following the existing build-layer-N pattern) and bump "
            f"MAX_SUPPORTED_LAYERS in plan.py before adding a base image this deep -- "
            f"otherwise the deepest images would silently never be planned at all."
        )

    return layers


def matching_dir(changed_file, dir_):
    d = dir_.rstrip("/")
    return changed_file == d or changed_file.startswith(d + "/")


def build_plan(images, changed_images=None):
    """Returns:
      {
        "layers": [ [image_record, ...], ... ],  # dependency order, base-most first
        "num_layers": int,
        "image_names": [str, ...],               # flat, in layer order
        "trigger": "selective" | "none",
      }
    Each image_record is the image's images.yaml dict PLUS:
      base_name, base_tag    -- parsed from `base`
      base_freshly_built     -- true iff base_name is ALSO in this plan (i.e.
                                 being built in an earlier layer of this SAME
                                 run). Either way build_image.sh resolves the
                                 base's digest LIVE from the registry: true =
                                 from the image just pushed this run; false =
                                 from the base's published (unchanged) tag.

    `changed_images` is a list of image NAMES that are already known to have
    changed -- i.e. the output of the sibling `changed_images.py` helper,
    which is the ONLY thing in this CI that decides WHETHER an image
    changed (by reading each image's published org.opencontainers.image.
    revision label and diffing its own dir + the shared build inputs +
    the .github/ machinery since that commit -- see that module's header).
    This function does not know or care WHY a name is in the list; it only
    ever does two PURE things with it:
      1. seed `direct` with exactly those names (every name must exist in
         the catalog -- an unknown name is a hard error, the same class of
         mistake as a typo'd `base:` reference, below);
      2. CASCADE: transitively add anyone whose base (direct or
         already-cascaded) is in the selected set -- but ONLY if that
         dependent image is `live`. A cascade is an AUTOMATIC rebuild
         triggered by the base moving, which is exactly the class of
         automatic rebuild `live: false` opts out of. A DIRECT edit to a
         non-live image's own files still builds it (that is an
         intentional, explicit change, not an automatic one) -- `direct`
         is never filtered by `live` for that reason.
    """
    all_layers = topological_order(images)
    by_name = {img["name"]: img for img in images}

    changed_images = changed_images or []
    unknown = sorted(set(changed_images) - set(by_name))
    if unknown:
        raise ValueError(
            f"--changed-image named {unknown}, which do not exist in the "
            f"catalog (typo, or a stale name from a since-renamed image?). "
            f"Known image names: {sorted(by_name)}."
        )
    direct = set(changed_images)

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
            # Normalized so the build step never has to decide: the docker
            # build context, defaulting to `dir` when the catalog omits it
            # (rbase, the 2.5 monolith). The per-chapter split images set it,
            # because their Dockerfile's COPY paths resolve against the
            # shared context root, not against the chapter directory the
            # Dockerfile sits in.
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


def chapter_image_rows(images):
    """[(chapter, 'name:tag', renders_qmd), ...] for --chapter-images -- one
    row per rendered .qmd, for BOTH the single-string and list forms of
    `renders`. Preserves catalog order, and within a list-form record,
    list order (never sorted). The chapter id is each .qmd's own stem --
    for the string form this equals the dir basename (validate_catalog has
    already proven the two agree), but a list-form record's dir basename
    is the GROUP name, not any one chapter's, so the stem is the only
    correct source for the chapter id there."""
    rows = []
    for img in images:
        renders = img.get("renders")
        if not renders:
            continue          # the common base renders no single .qmd
        render_list = [renders] if isinstance(renders, str) else renders
        for r in render_list:
            chapter = r.rsplit("/", 1)[-1][: -len(".qmd")]
            rows.append((chapter, f"{img['name']}:{img['tags'][0]}", r))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    # Repeatable: the catalog is split across files by ownership (hand-
    # maintained root vs generated per-phase), but base edges cross them, so
    # the planner must be given every file that makes up the one logical
    # catalog. See load_catalogs.
    ap.add_argument("--images-yaml", required=True, action="append",
                    dest="images_yaml_paths",
                    help="catalog file; repeat for each file in the catalog")
    # Repeatable: the already-resolved CHANGED image names -- the output of
    # .github/scripts/changed_images.py, which is the only thing in this CI
    # that decides whether an image changed (git diff + registry). This
    # module never re-derives that decision from raw file paths; see
    # build_plan()'s docstring.
    ap.add_argument("--changed-image", action="append", default=[], dest="changed_images")
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
        for chapter, image_tag, r in chapter_image_rows(images):
            print(f"{chapter}\t{image_tag}\t{r}")
        return

    result = build_plan(images, changed_images=args.changed_images)
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
