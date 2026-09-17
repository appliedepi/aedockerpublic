#!/usr/bin/env python3
# generate_groups.py: the v2.9 group-image package-list generator.
#
# THE LAYOUT IS THE MEMBERSHIP
#
# Every chapter owns a package list. That list lives in the directory of the
# group image that renders the chapter, named packages_cran_<stem>.txt. The
# location of the file assigns the chapter to the group. No separate
# assignment file exists.
#
# A hand-maintained YAML file held that assignment until 2026-09-17. It is
# deleted, and CHANGELOG.md names it. A second file that states the same fact
# can disagree with the layout, and a reader cannot tell which one is true.
#
# The assignment itself stays an editorial decision. Nothing derives it. A
# chapter renders with the group image that owns its part of the book. gis is
# the 50th stem, and it joined `analysis` on 2026-09-02 for that reason.
#
# A group's own package list is GENERATED, never hand-maintained, because it
# is a union over a set that changes. Every change to one chapter's footprint
# changes every group list that holds that chapter. A hand-maintained union
# drifts the moment one of its 8 to 11 inputs moves and nobody re-unions it.
# The generator makes "the group list matches its members" a checked
# invariant. See --check below.
#
# NAMES
#
# Group keys use HYPHENS, because they become Docker image name components.
# Chapter stems use UNDERSCORES, because they are the stems of the handbook
# source files, content/en/<stem>.qmd. Neither spelling is normalised to the
# other. Both are load-bearing exactly as written.
#
# INPUTS (read-only):
#   groups/<group>/packages_cran_<stem>.txt
#       One chapter's own FULL package list, one bare CRAN or Bioconductor
#       name per line, with no comments and no blank lines. There are 50 of
#       them. The 48 chapters that had a 2.7 image carry the list their 2.7
#       footprint capture produced, copied here unchanged on 2026-09-02. gis
#       was captured the same way in 2.8. One file is empty: see the NOTE on
#       the "errors" chapter below.
#   images.yaml
#       The v2.9 image catalog, in this directory. Each group image lists the
#       chapters it renders under `renders`, as content/en/<stem>.qmd entries.
#       check_membership below compares those lists against the layout, in
#       both directions and group by group.
#
# OUTPUTS (all generated; do not hand-edit, rerun this script instead):
#   groups/<group>/packages_cran.txt   (6 files, one per group directory)
#   monolith/packages_cran.txt         (1 file: union of the 6 group files)
#
# A group's generated list sits beside its member lists. The generated one is
# the file with no _<stem> in its name, and that is the only difference. Do
# not hand-edit it.
#
# The monolith sits BESIDE groups/, not inside it. It is not a group: it
# renders no chapter, and it exists for the .devcontainer.json. A `groups`
# path segment would make plan.py demand a `renders` list it cannot have. The
# 6 groups already claim all 50 chapters, and no .qmd may be claimed twice.
#
# METHOD: do NOT subtract the shared `common` base (common/packages_cran.txt)
# from anything here. v2.7's own chapter Dockerfiles install each chapter's
# FULL footprint on top of `common`. They rely on pak's already-installed
# skip (dependencies=FALSE, exact-version match) to make that a true no-op
# for whatever common already covers. That is what makes each v2.7 chapter
# image a strict superset of its footprint BY CONSTRUCTION. See 2.6's
# generate.py chapter_dockerfile, in git history, for the original statement
# of the property; v2.7 inherited it unchanged. A group list built by plain
# UNION of its members' full lists keeps that superset property for free. A
# union of supersets is still a superset of every member. Subtracting common
# first and re-adding it later would not be wrong on its own. It is one extra
# derived step this script has no reason to take: nothing here needs the
# subtracted form.
#
# NOTE on the "errors" chapter: it has no executable R chunks, so its
# footprint IS the empty set and its packages_cran_errors.txt is an empty
# file. An empty file is a chapter that needs nothing beyond common. A
# MISSING file is a hard error, and check_membership raises it. The chapter
# still appears under its image's `renders`, so the layout no longer covers
# what that image builds.
#
# DETERMINISM: package names are sorted with plain sorted(). Python's default
# order is by Unicode code point. The package names here are ASCII only, so
# that order is byte-identical to the C-locale `sort` order the member lists
# already use. Directory listings decide membership now. Every os.listdir()
# result is sorted before it is used. Every list of names is unioned into a
# set and re-sorted before it is written. Nothing here reads wall-clock time,
# randomness, or raw directory order for its file CONTENTS. Re-running this
# script against unchanged inputs reproduces byte-identical output.
#
# CLI:
#   python3 generate_groups.py           # write the 7 files
#   python3 generate_groups.py --check   # regenerate in memory, diff against
#                                        # the committed files; exit 1 (with
#                                        # the diff, on stderr) on any
#                                        # difference. This is what CI runs.
import argparse
import difflib
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
# images.yaml states every `dir` relative to the repository root, and this
# script sits two levels below that root, at epirhandbook/2.9.
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
GROUPS_DIR = os.path.join(HERE, "groups")
IMAGES_YAML = os.path.join(HERE, "images.yaml")

# The one generated list in a group directory. Every other packages_cran file
# there is a member list, one chapter each.
GENERATED_LIST = "packages_cran.txt"
# Both patterns below anchor with \A and \Z, never ^ and $. Python's $ also
# matches immediately BEFORE a final newline, so `^...$` accepts
# 'content/en/gis.qmd\n'. A YAML block scalar produces exactly that value, and
# the match here must be exact.
MEMBER_LIST = re.compile(r"\Apackages_cran_(?P<stem>.*)\.txt\Z")
# A `renders` entry names the main-language source file and nothing else.
RENDERS_ENTRY = re.compile(r"\Acontent/en/(?P<stem>[^/]+)\.qmd\Z")


def discover_layout():
    """Read the layout under groups/ -> {group_key: {stem: path}}.

    A group is an immediate subdirectory of groups/. Its members are the
    immediate files in it named packages_cran_<stem>.txt. The group's own
    generated packages_cran.txt is an output, so it is never a member, and
    the Dockerfile beside it is not one either.
    """
    if not os.path.isdir(GROUPS_DIR):
        raise ValueError(f"{GROUPS_DIR} does not exist: there is no layout to read.")

    layout = {}
    for key in sorted(os.listdir(GROUPS_DIR)):
        group_dir = os.path.join(GROUPS_DIR, key)
        if not os.path.isdir(group_dir):
            continue
        members = {}
        for fn in sorted(os.listdir(group_dir)):
            if fn == GENERATED_LIST:
                continue
            full = os.path.join(group_dir, fn)
            if not os.path.isfile(full):
                continue
            match = MEMBER_LIST.match(fn)
            if match is None:
                continue
            stem = match.group("stem")
            if not stem:
                raise ValueError(
                    f"{full} names an empty chapter stem. A member list is "
                    f"packages_cran_<stem>.txt, and <stem> must not be empty."
                )
            members[stem] = full
        layout[key] = members

    claimed = {}
    for key in sorted(layout):
        for stem in sorted(layout[key]):
            if stem in claimed:
                raise ValueError(
                    f"chapter stem {stem!r} has a package list in two groups: "
                    f"{claimed[stem]!r} and {key!r}. Every chapter must have "
                    f"exactly one list, in the directory of the group image "
                    f"that renders it."
                )
            claimed[stem] = key
    return layout


def load_renders(path):
    """images.yaml -> {group_key: {stem, ...}}, for the group images only.

    A group image is an image whose `dir` is an immediate subdirectory of
    this script's groups/ directory. That test reads `dir` alone. It never
    asks whether `renders` is a list, because an image that must carry a
    `renders` list and does not is drift this check exists to catch.
    epirhandbook-common, epirhandbook-monolith and rbase all build a
    directory outside groups/, so they are skipped and their absent
    `renders` is correct.
    """
    with open(path) as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict) or not isinstance(doc.get("images"), list):
        raise ValueError(
            f"{path}: the top level must be a mapping holding an 'images' "
            f"list; got {doc!r}"
        )

    expected = {}
    for image in doc["images"]:
        if not isinstance(image, dict) or not isinstance(image.get("dir"), str):
            raise ValueError(
                f"{path}: every image record must be a mapping with a string "
                f"'dir'; got {image!r}"
            )
        image_dir = os.path.normpath(os.path.join(REPO_ROOT, image["dir"]))
        if os.path.dirname(image_dir) != GROUPS_DIR:
            continue
        key = os.path.basename(image_dir)
        name = image.get("name", key)
        if key in expected:
            raise ValueError(
                f"{path}: two images build the group directory {image['dir']!r}. "
                f"Exactly one image builds each group."
            )

        renders = image.get("renders")
        if not isinstance(renders, list) or not renders:
            raise ValueError(
                f"{path}: image {name!r} builds the group directory "
                f"{image['dir']!r}, so it must carry a non-empty list-form "
                f"'renders'; got {renders!r}"
            )
        stems = []
        for entry in renders:
            match = RENDERS_ENTRY.match(entry) if isinstance(entry, str) else None
            if match is None:
                raise ValueError(
                    f"{path}: image {name!r} carries the 'renders' entry "
                    f"{entry!r}. Every entry must be exactly "
                    f"content/en/<stem>.qmd, with no extra path segment."
                )
            stems.append(match.group("stem"))
        # Detect a repeat on the LIST. A set would absorb it silently.
        repeated = sorted({s for s in stems if stems.count(s) > 1})
        if repeated:
            raise ValueError(
                f"{path}: image {name!r} lists chapter stem(s) {repeated} more "
                f"than once under 'renders'. Every entry must appear once."
            )
        expected[key] = set(stems)

    if not expected:
        raise ValueError(
            f"{path}: no image builds a directory under {GROUPS_DIR}, so there "
            f"is nothing to check the layout against."
        )

    claimed = {}
    for key in sorted(expected):
        for stem in sorted(expected[key]):
            if stem in claimed:
                raise ValueError(
                    f"{path}: chapter stem {stem!r} is rendered by both group "
                    f"{claimed[stem]!r} and group {key!r}. No chapter may be "
                    f"claimed twice."
                )
            claimed[stem] = key
    return expected


def check_membership(layout, expected):
    """Fail on any disagreement between the layout under groups/ and the
    `renders` lists in images.yaml, in BOTH directions and group by group.

    The comparison is per group, never global. A global stem-set comparison
    passes when a chapter's list sits under the wrong group, which is the
    drift a reader is least likely to spot by eye.

    It catches, in either direction:
      - a group directory that no image builds, or an image group directory
        that does not exist;
      - a chapter an image renders with no package list in that image's own
        directory, which is a chapter silently dropping out of the product;
      - a package list in a group directory whose chapter that group's image
        does not render, which is a typo'd stem, a stale file, or a chapter
        filed under the wrong group.
    """
    problems = []

    only_layout = sorted(set(layout) - set(expected))
    if only_layout:
        problems.append(
            f"{GROUPS_DIR} holds group directories {only_layout} that no image "
            f"in {IMAGES_YAML} builds."
        )
    only_images = sorted(set(expected) - set(layout))
    if only_images:
        problems.append(
            f"{IMAGES_YAML} names group directories {only_images} that do not "
            f"exist under {GROUPS_DIR}."
        )

    for key in sorted(set(layout) & set(expected)):
        have = set(layout[key])
        want = expected[key]
        missing = sorted(want - have)
        if missing:
            problems.append(
                f"group {key!r}: its image renders chapter(s) {missing}, but "
                f"groups/{key}/ holds no packages_cran_<stem>.txt for them."
            )
        extra = sorted(have - want)
        if extra:
            problems.append(
                f"group {key!r}: groups/{key}/ holds a package list for "
                f"chapter(s) {extra}, which this group's image does not render."
            )

    if problems:
        raise ValueError(
            "the group layout and images.yaml disagree:\n  "
            + "\n  ".join(problems)
            + f"\nEvery chapter's package list must sit in the directory of the "
            f"group image that renders it, and every chapter an image renders "
            f"must have one. Move the file, or fix the image's `renders` list "
            f"in {IMAGES_YAML}."
        )


def read_member_packages(path):
    """One chapter's own full package list: bare package names, one per line,
    no comments, no blank lines (true of all 50 files, verified).

    An EMPTY file is legitimate. Today only `errors` has one, because that
    chapter runs no R and needs nothing beyond `common`.
    """
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def build(layout):
    """The layout -> {output relative path: [sorted package names], ...} for
    all 7 outputs (6 groups + monolith). Pure computation, no filesystem
    writes. The write path and --check share this function, so the check can
    never drift from what a real run would produce."""
    outputs = {}
    monolith = set()
    for key in sorted(layout):
        pkgs = set()
        for stem in sorted(layout[key]):
            pkgs.update(read_member_packages(layout[key][stem]))
        outputs[f"groups/{key}/{GENERATED_LIST}"] = sorted(pkgs)
        monolith.update(pkgs)
    outputs[f"monolith/{GENERATED_LIST}"] = sorted(monolith)
    return outputs


def render(names):
    return "".join(f"{p}\n" for p in names)


def write_outputs(outputs):
    for rel, names in outputs.items():
        path = os.path.join(HERE, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(render(names))


def check(outputs):
    """Diff freshly-computed `outputs` against the COMMITTED files on disk.
    Returns a list of (relative_path, unified_diff_text) for every path that
    differs. That includes a wanted file missing on disk, and a committed
    file under groups/ that `outputs` no longer wants at all, which is a
    stale list left behind by a group that has gone. Empty list = clean."""
    on_disk_rel = set()
    if os.path.isdir(GROUPS_DIR):
        for root, _dirs, files in os.walk(GROUPS_DIR):
            for fn in files:
                if fn != GENERATED_LIST:
                    continue  # Dockerfiles and member lists live here too
                full = os.path.join(root, fn)
                on_disk_rel.add(os.path.relpath(full, HERE))

    problems = []
    for rel in sorted(set(outputs) | on_disk_rel):
        full = os.path.join(HERE, rel)
        committed = None
        if os.path.isfile(full):
            with open(full) as f:
                committed = f.read()
        wanted = render(outputs[rel]) if rel in outputs else None
        if committed != wanted:
            diff = "".join(
                difflib.unified_diff(
                    (committed or "").splitlines(keepends=True),
                    (wanted or "").splitlines(keepends=True),
                    fromfile=f"{rel} (committed)",
                    tofile=f"{rel} (regenerated)",
                )
            )
            problems.append((rel, diff))
    return problems


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory and diff against the committed files; "
        "exit 1 (with the diff, on stderr) on any difference. What CI runs.",
    )
    args = ap.parse_args()

    # Membership first, in both modes. A layout that disagrees with
    # images.yaml must stop the run before any union is built, because a
    # union hides the disagreement: a chapter that needs nothing beyond
    # common, such as `errors`, shifts no group list at all.
    layout = discover_layout()
    check_membership(layout, load_renders(IMAGES_YAML))
    outputs = build(layout)

    if args.check:
        problems = check(outputs)
        if problems:
            for rel, diff in problems:
                print(f"--- DRIFT: {rel} ---", file=sys.stderr)
                print(diff, file=sys.stderr)
            print(
                f"generate_groups.py --check: {len(problems)} file(s) differ "
                f"from the committed output -- rerun 'python3 generate_groups.py' "
                f"and commit the result.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"generate_groups.py --check: OK, {len(outputs)} files match committed output.")
        return

    write_outputs(outputs)
    print("group\tchapters\tpackages")
    for key in sorted(layout):
        n = len(outputs[f"groups/{key}/{GENERATED_LIST}"])
        print(f"{key}\t{len(layout[key])}\t{n}")
    print(f"monolith\t{len(layout)} groups\t{len(outputs[f'monolith/{GENERATED_LIST}'])}")


if __name__ == "__main__":
    main()
