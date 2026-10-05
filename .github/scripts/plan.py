#!/usr/bin/env python3
"""CI planner: images.yaml and a list of image names already known to have
changed -> the ordered set of images to build.

This module is pure logic. It does not depend on GitHub Actions, subprocess,
the registry or git, so unit tests call it directly (see test_plan.py). This
is the part of the CI most likely to be wrong, and its faults are hard to see
in a real Actions run. The decision about which images changed needs git and
the registry. That decision lives only in the sibling `changed_images.py`.
This module reads its output, a list of image names. It never computes the
decision again, and it never calls git or the registry.

Loading images.yaml has two stages, and neither is a hand-written parser.
Real PyYAML (`yaml.safe_load`, hash-pinned, see requirements.txt) parses the
file. Then validate_catalog() below applies a strict allowlist schema to the
result. This replaced a narrow vendored YAML reader (`minimal_yaml.py`, now
deleted). That reader tried to give "the same meaning as real YAML, or
raise". That goal has no bound: YAML's implicit scalars (dates, hex,
booleans, floats, ...) are more than any hand-written rejection list can
cover. Three more review rounds found blockers where the reader differed
from real YAML. In total, four rounds went to this one question (CHANGELOG.md,
phase 4 log, 8.9 and 8.4/8.8). The new contract has a bound. PyYAML parses,
the schema checks each field against one declared type, and anything else is
a hard error. This module never tries to parse YAML itself.

CLI:
    python3 plan.py --images-yaml images.yaml --changed-image name-a --changed-image name-b
Prints one JSON object to stdout. See the docstring of build_plan() for the
shape.
"""
import argparse
import json
import re
import sys

import yaml

# A fixed limit that matches the jobs in build.yml (build-layer-0 ..
# build-layer-3, so 4 layers). It is a hard limit: a catalog that needs a 5th
# layer MUST NOT be cut short without an error. The catalog holds 9 images
# today in 3 layers, so the 4-layer limit leaves one spare. A dropped layer is
# a partial publish with no error: some images are never built. See the check
# in topological_order() below, and the test in test_plan.py for a catalog
# deeper than this.
MAX_SUPPORTED_LAYERS = 4


def parse_base(base):
    """'rbase:4.3.2' -> ('rbase', '4.3.2'). None/empty -> ('', '')."""
    if not base:
        return "", ""
    name, _, tag = base.rpartition(":")
    if not name:
        # No ':' is present, so the whole string is the name, with no tag.
        return base, ""
    return name, tag


REQUIRED_IMAGE_KEYS = {"name", "dir", "tags", "base", "description"}
# `description`: one line about the image. build_image.sh stamps it as the
# org.opencontainers.image.description label. It is REQUIRED. If it were
# optional, a record without it would publish with the description it
# inherits from its base. For rbase, that is Canonical's text for ubuntu, and
# nothing would fail.
# `renders`: the .qmd file, or the list of .qmd files, that this image renders,
# relative to the handbook source root. 2.9 uses the list form on its six
# group images. The field is optional: rbase, epirhandbook-common and the
# monolith render nothing. It names the real file, not an abstract chapter
# id. For the string form, the validator below
# checks the stem against the `dir` basename. For the list form, it checks
# the image name against that basename. Both checks tie the field to its
# build context.
# `context`: the docker build context, when it differs from `dir`. These are
# two different facts:
#   dir     = this image's own files: the change-detection scope, and the
#             directory of its Dockerfile.
#   context = the directory given to `docker build`, which is the root that
#             COPY paths resolve against.
# For rbase they are the same, so `context` is omitted. Every image in
# epirhandbook/2.9/images.yaml sets it to epirhandbook/2.9, because the two
# differ there. Each Dockerfile is in the image's own `dir`. It
# COPYs pak_install_subset.R from the 2.9 root, and reaches its own
# packages_cran.txt by a path relative to that root. Change detection stays
# per image, on `dir`. A build with the image's own dir as context fails,
# because the COPY sources are outside it.
OPTIONAL_IMAGE_KEYS = {"live", "renders", "context"}
ALLOWED_IMAGE_KEYS = REQUIRED_IMAGE_KEYS | OPTIONAL_IMAGE_KEYS

# Image-name-safe: what is legal in a Docker/GHCR image name component.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
# A single Docker tag, by the OCI/Docker rule: first char [a-zA-Z0-9_], then
# up to 127 of [a-zA-Z0-9_.-]. This excludes the comma, the slash and
# whitespace. The workflow joins an image's tags with join(','), and
# build_image.sh splits them again on ','. So a tag that contains a comma
# (`"prod,latest"`) would become two published tags with no error. A
# malformed field would then change what CI publishes. With this charset,
# such a tag cannot exist, so no later step needs to catch it.
TAG_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}$")
# A base reference: "<name>:<tag>". Both halves are non-empty, and each obeys
# its own charset. Before this rule, `base: "rbase:"` (empty tag) reached the
# build with an empty base tag. So the rule needs a real tag after the colon.
BASE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*:[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}$")
# A repo-relative build-context dir, in canonical form: one or more path
# segments of a shell-safe charset, joined by single '/'. It has no leading or
# trailing slash and no empty segment. `dir` is the Docker build context when
# `context` is omitted (rbase). It is always the selective-change matcher:
# matching_dir compares it, unchanged, against changed file paths. A
# non-canonical form can pass validation and never match. For example,
# `./rbase/4.3.2` passes an "is it relative?" check, but never matches the
# changed file `rbase/4.3.2/Dockerfile`. CI then skips the rebuild with no
# error. The canonical form makes the stored dir equal to what git reports.
# The code below rejects '.' and '..' segments, because the charset alone
# allows them.
DIR_RE = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")


def _label(image, index):
    """A name for error messages: the image's own `name` field when it is
    usable, else its position in the list. The `name` field can itself be
    the missing or malformed value."""
    if isinstance(image, dict) and isinstance(image.get("name"), str) and image["name"]:
        return image["name"]
    return f"images[{index}]"


def validate_catalog(doc, path):
    """A strict allowlist schema over the output of
    yaml.safe_load(images.yaml). It rejects anything that it does not
    permit. It does not try to list everything that can be wrong:
    minimal_yaml.py used that denylist approach and failed (see this
    module's docstring). Each field has one declared type. Anything else is
    a hard ValueError that names the file, the image, the field and the
    expected value. On success, it returns the validated `images` list,
    unchanged, in the shape that callers expect."""
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

    # Image names MUST be unique. Every later structure uses the name as key
    # (by_name = {img["name"]: img ...} in topological_order and build_plan).
    # So a duplicate name keeps only the last record, with no error. A change
    # under the first record would then plan the dir and tags of the second.
    # The check is here because only here is the whole catalog in view. A
    # per-image check cannot see the clash.
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
        # PyYAML turns an unquoted 2024-01-01 into a datetime.date, and
        # 0x10 or 2.5 into a number. This check finds those cases. The
        # schema needs a string, so it rejects any other type that YAML
        # gives. plan.py does not need to list YAML's implicit-scalar
        # grammar.
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

    # `description` goes to a public registry unchanged, as this image's
    # org.opencontainers.image.description OCI label. It MUST be a string
    # with content: a value of only whitespace is an empty label.
    description = image["description"]
    if not isinstance(description, str) or not description.strip():
        raise ValueError(
            f"{path}: image {label!r} field 'description' must be a non-empty "
            f"string; got {description!r}. It is published as this image's "
            f"org.opencontainers.image.description OCI label."
        )
    # The catalog header states "One line about the image". This check
    # enforces it, so no future editor can break it. A description on more
    # than one line reaches `docker inspect` with an escape in it, and the
    # registry page shows it broken. (An OCI label value MAY contain a
    # newline. The one-line rule is this project's presentation contract,
    # not a format limit.)
    #
    # Use Python's definition of a line, not a test for "\n" and "\r". YAML
    # double-quoted escapes arrive here as U+000B, U+000C, U+0085, U+2028 and
    # U+2029. `splitlines()` treats each of them as a line boundary, and a
    # hand-written newline test does not. The second clause finds a common
    # case that the first misses: a block scalar gives 'text\n', and
    # 'text\n'.splitlines() is a one-element list.
    lines = description.splitlines()
    if len(lines) != 1 or lines[0] != description:
        raise ValueError(
            f"{path}: image {label!r} field 'description' must be ONE line; "
            f"got {description!r}. It is published as this image's "
            f"org.opencontainers.image.description OCI label."
        )

    # `renders`: the .qmd file, or the list of .qmd files, this image renders.
    # In the string form, the stem MUST equal the last segment of `dir`.
    # That directory is the image's own dir. If they differ, the record names
    # two different chapters, and one is wrong. The list form cannot use that
    # rule, because a group's dir basename is the group name, not the name of
    # one chapter. So it checks the image name against that basename. Each
    # check ties the field to the image's own dir, so the two cannot disagree.
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
            # The name MUST identify the group this record renders: its dir
            # basename, lowercased. This is the list-form match for the
            # string-form chapter check below. Without it, a row could render
            # {regression,stat_tests}.qmd from groups/analysis and publish as
            # `epirhandbook-wrong-group`. It would pass validation, and a
            # public registry would show a false name.
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
            # The name MUST also match that chapter. A check of source against
            # dir alone puts no limit on the published name. A row could
            # render basics.qmd from chapters/basics and publish as
            # `epirhandbook-cleaning`. It would pass validation, and a public
            # registry would show a false name. The name is the chapter in
            # lowercase. Docker needs lowercase, and only this check applies
            # that change.
            if not image["name"].endswith(f"-{renders_stem.lower()}"):
                raise ValueError(
                    f"{path}: image {label!r} renders {renders!r} but its name does "
                    f"not end with '-{renders_stem.lower()}'. The published image name "
                    f"must identify the chapter it renders, or the registry artifact "
                    f"misrepresents its own content."
                )

    # A per-chapter or per-group image MUST declare what it renders.
    # `renders` is optional in general: rbase, epirhandbook-common and
    # epirhandbook-monolith render nothing. A row whose dir has a `chapters`
    # or `groups` path segment is always a per-chapter or per-group image.
    # Without `renders`, that row would skip all the stem/name/dir checks,
    # and it could publish under any name. The match is by segment (dir split
    # on '/'), not by substring. A substring match on '/chapters/' or
    # '/groups/' would miss a dir that is only "chapters" or "groups". It
    # would also miss a dir where that segment comes first, with no
    # leading '/'.
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

    # `context`: the same canonical-path rules as `dir`, and `dir` MUST be
    # inside it. The build selects the Dockerfile with `-f <dir>/Dockerfile`
    # against this context, so a dir outside the context cannot build.
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
    """Read one images.yaml -> the validated list[dict] of image records.
    PyYAML parses, and validate_catalog() enforces the schema. This
    module's docstring gives the reason for the two stages. No other code
    path in this project reads images.yaml. build_image.sh only receives
    values that this plan already validated, as CLI args."""
    with open(images_yaml_path) as f:
        doc = yaml.safe_load(f)
    return validate_catalog(doc, images_yaml_path)


def load_catalogs(paths):
    """Merge several catalog files into the one logical catalog that the
    planner uses.

    Both files are hand-maintained. The root images.yaml holds the base
    image, rbase. The file epirhandbook/2.9/images.yaml holds the 2.9 line:
    epirhandbook-common, the six group images and the monolith.

    The planner MUST see one catalog, because base edges cross the files:
    epirhandbook-common (2.9) is FROM rbase (root). If only one file loads,
    `rbase` looks like a typo, and the plan fails.

    Each image is defined in one file only. A name in two catalogs is a hard
    error. The same rule forbids a duplicate within one file."""
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
            # Two images MUST NOT render the same .qmd. The check covers the
            # whole combined catalog: all --images-yaml files together, not
            # one file at a time. Two images could publish the same page under
            # two different names, and each would look correct alone. The
            # check compares raw strings as written in `renders`, as
            # validate_catalog does elsewhere. `renders` has no
            # canonical-form rule.
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
    """Layers from Kahn's algorithm over the base edges of the full
    catalog, not only a changed subset. So the layer order is a fixed
    property of the catalog. It does not depend on which images a run
    changes.

    Returns a list of layers. Each layer is a list of image dicts. The order
    within a layer has no meaning, because there are no edges between them.
    Raises ValueError on a cycle, an unknown base name, or more layers than
    the workflow files support. A real catalog should never cause these. The
    function fails with an error so that it never drops images.
    """
    by_name = {img["name"]: img for img in images}

    # Validate every base reference before the sort. Without this check,
    # the Kahn's-algorithm loop below cannot tell an unknown base name (a
    # typo in `base:`) from "this image has no base". `base_name not in
    # remaining` is true in two cases. In one, an earlier layer already
    # holds the base, which is correct. In the other, the base is not an
    # image at all, which is a typo. The typo would drop the cascade edge
    # with no error. The image would build as if it had no base. Then it
    # would never rebuild when its base rebuilds, which is the purpose of
    # `base`. So the function raises an error.
    for name, img in by_name.items():
        base_name, _ = parse_base(img.get("base"))
        if base_name and base_name not in by_name:
            raise ValueError(
                f"image '{name}' has base '{img.get('base')}', but no image named "
                f"'{base_name}' exists in the catalog (typo?). Known image names: "
                f"{sorted(by_name)}."
            )

    remaining = dict(by_name)
    layers = []
    while remaining:
        # An image is ready when its base is not in `remaining`. Either an
        # earlier layer holds the base, or the image has no base in the
        # catalog.
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
      base_name, base_tag    : parsed from `base`
      base_freshly_built     : true iff base_name is also in this plan, so
                               an earlier layer of this run builds it.
                               In both cases build_image.sh resolves the
                               base's digest from the registry at build
                               time. If true, it uses the image this run
                               pushed. If false, it uses the base's
                               published, unchanged tag.

    `changed_images` is a list of image names already known to have
    changed. It is the output of the sibling `changed_images.py` helper.
    That helper is the only part of this CI that decides whether an image
    changed. It reads each image's published
    org.opencontainers.image.revision label. Then it diffs the image's own
    dir, the shared build inputs and the .github/ machinery since that
    commit (see the header of that module). This function does not use the
    reason that a name is in the list. It does two pure things with it:
      1. Put those names in `direct`. Every name MUST exist in the catalog.
         An unknown name is a hard error, the same kind of mistake as a
         typo in a `base:` reference (below).
      2. Cascade: add, transitively, each image whose base is in the
         selected set, from `direct` or from an earlier cascade step. Add it
         only if that dependent image is `live`. A cascade is an automatic
         rebuild because the base moved, and `live: false` turns off that
         kind of rebuild. A direct edit to a non-live image's own files
         still builds it, because that change is intentional. So `live`
         never filters `direct`.
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
            # The docker build context, set here so the build step never
            # decides it. It defaults to `dir` when the catalog omits it.
            # Only rbase omits it. The eight images in
            # epirhandbook/2.9/images.yaml all set it. The COPY paths in
            # their Dockerfiles resolve against the shared epirhandbook/2.9
            # root, not against the directory of the Dockerfile.
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
    """[(chapter, 'name:tag', renders_qmd), ...] for --chapter-images: one
    row per rendered .qmd, for both the string and list forms of `renders`.
    It keeps catalog order, and list order within a list-form record. It
    never sorts. The chapter id is the stem of each .qmd. For the string
    form, the stem equals the dir basename, because validate_catalog
    already checked that. For a list-form record, the dir basename is the
    group name, not the name of one chapter. So there the stem is the only
    correct source for the chapter id."""
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
    # Repeatable: the catalog is split across two hand-maintained files. Base
    # edges cross them, so the planner needs every file of the one logical
    # catalog. See load_catalogs.
    ap.add_argument("--images-yaml", required=True, action="append",
                    dest="images_yaml_paths",
                    help="catalog file; repeat for each file in the catalog")
    # Repeatable: the image names already resolved as changed. They are the
    # output of .github/scripts/changed_images.py, the only part of this CI
    # that decides whether an image changed (git diff and registry). This
    # module never derives that decision again from raw file paths. See the
    # docstring of build_plan().
    ap.add_argument("--changed-image", action="append", default=[], dest="changed_images")
    # For shell consumers (build and render loops): print
    # "chapter<TAB>image:tag<TAB>renders" for every row that names a
    # chapter. A script
    # uses this to learn which image renders which chapter. A script MUST NOT
    # build "epirhandbook-<chapter>:<tag>" itself. Otherwise the naming rule
    # would live in the catalog and in every consumer, and the single-source
    # catalog exists to prevent that copy.
    ap.add_argument("--chapter-images", action="store_true",
                    help="print 'chapter<TAB>image:tag<TAB>renders' per chapter row and exit")
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
