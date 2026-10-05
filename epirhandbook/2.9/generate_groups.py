#!/usr/bin/env python3
# generate_groups.py: the v2.9 generator for the group-image package lists.
#
# THE LAYOUT IS THE MEMBERSHIP
#
# Every chapter has its own package list. The list is in the directory of the
# group image that renders the chapter, as packages_cran_<stem>.txt. The
# location of that file assigns the chapter to the group. There is no separate
# assignment file.
#
# Until 2026-09-17, a hand-maintained YAML file held the assignment. That file
# is deleted, and CHANGELOG.md records the deletion. A second file that states
# the same fact can disagree with the layout, and then a reader cannot tell
# which one is true.
#
# The assignment is an editorial decision, and no code derives it. A chapter
# renders with the group image that owns its part of the book. For that
# reason, gis, the 50th stem, joined `analysis` on 2026-09-02.
#
# This script generates the package list of each group. Nobody edits it by
# hand, because it is a union over a set that changes. A change to one
# chapter's list changes the list of the group that holds that chapter. A
# hand-maintained union goes stale when one of its 8 to 11 inputs changes and
# nobody makes the union again. With the generator, "the group list matches
# its members" is a checked invariant. See --check below.
#
# NAMES
#
# Group keys use HYPHENS, because they become components of Docker image
# names. Chapter stems use UNDERSCORES, because they are the stems of the
# handbook source files, content/en/<stem>.qmd. The script does not convert
# one spelling to the other. Both MUST stay as written.
#
# INPUTS (read-only):
#   groups/<group>/packages_cran_<stem>.txt
#       The FULL package list of one chapter: one bare CRAN or Bioconductor
#       name per line, with no comments and no blank lines. There are 50 of
#       these files. The 48 chapters that had a 2.7 image use the list from
#       their 2.7 footprint capture, copied here unchanged on 2026-09-02. The
#       gis list came from the same capture method in 2.8. One file is empty:
#       see the NOTE on the "errors" chapter below.
#   images.yaml
#       The v2.9 image catalog, in this directory. Each group image lists the
#       chapters it renders under `renders`, as content/en/<stem>.qmd entries.
#       check_membership below compares those lists with the layout, group by
#       group and in both directions.
#
# OUTPUTS (all generated. Do not edit them by hand. Run this script again.):
#   groups/<group>/packages_cran.txt   (6 files, one per group directory)
#   monolith/packages_cran.txt         (1 file: union of the 6 group files)
#
# The generated list of a group is in the same directory as its member lists.
# The generated list is the file with no _<stem> in its name.
#
# The monolith is BESIDE groups/, not in it, because it is not a group. It
# renders no chapter, and it exists for the .devcontainer.json. If its path
# had a `groups` segment, plan.py would need a `renders` list from it, and it
# cannot have one. The 6 groups already claim all 50 chapters, and no .qmd
# can be claimed twice.
#
# METHOD: do NOT subtract the shared `common` base (common/packages_cran.txt)
# from any list here. In v2.7, each chapter Dockerfile installed the FULL
# footprint of its chapter on top of `common`. pak skips a package that is
# already installed (dependencies=FALSE, exact-version match), so the
# packages that common already holds cost nothing. Thus each v2.7 chapter
# image always holds every package of its footprint. The chapter_dockerfile
# function of 2.6's generate.py, in git history, first stated this property,
# and v2.7 kept it. A group list is the plain UNION of the full lists of its
# members. It keeps the property, because a union of supersets is a superset
# of each member. To subtract common first and add it again later is not
# wrong. It is an extra derived step, and nothing here needs the subtracted
# form.
#
# NOTE on the "errors" chapter: it has no executable R chunks. Its footprint
# is the empty set, so packages_cran_errors.txt is an empty file. An empty
# file means that the chapter needs nothing beyond common. A MISSING file is
# a hard error, and check_membership raises it. The chapter is still in the
# `renders` of its image, so the layout no longer covers what it builds.
#
# DETERMINISM: the script sorts package names with plain sorted(), which
# orders by Unicode code point. All package names here are ASCII, so this
# order is the same, byte for byte, as the C-locale `sort` order of the
# member lists. Directory listings decide membership. The script sorts each
# os.listdir() result before it uses it. It puts each list of names into a
# set and sorts the set again before it writes it. The CONTENTS of the output
# files do not depend on wall-clock time, randomness or raw directory order.
# A second run on unchanged inputs writes byte-identical output.
#
# CLI:
#   python3 generate_groups.py           # write the 7 files
#   python3 generate_groups.py --check   # generate in memory and compare with
#                                        # the committed files. On a
#                                        # difference, print the diff to
#                                        # stderr and exit 1. CI runs this.
import argparse
import difflib
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
# images.yaml gives every `dir` relative to the repository root. This script
# is two levels below that root, at epirhandbook/2.9.
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
GROUPS_DIR = os.path.join(HERE, "groups")
IMAGES_YAML = os.path.join(HERE, "images.yaml")

# The one generated list in a group directory. Each other packages_cran file
# there is the member list of one chapter.
GENERATED_LIST = "packages_cran.txt"
# Both patterns below anchor with \A and \Z, never ^ and $. In Python, $ also
# matches before a final newline, so `^...$` accepts 'content/en/gis.qmd\n'.
# A YAML block scalar gives that value, and the match here must be exact.
MEMBER_LIST = re.compile(r"\Apackages_cran_(?P<stem>.*)\.txt\Z")
# A `renders` entry names the main-language source file and nothing else.
RENDERS_ENTRY = re.compile(r"\Acontent/en/(?P<stem>[^/]+)\.qmd\Z")


def discover_layout():
    """Read the layout under groups/ -> {group_key: {stem: path}}.

    A group is an immediate subdirectory of groups/. Its members are the
    files directly in it that have the name packages_cran_<stem>.txt. The
    generated packages_cran.txt of the group is an output, so it is not a
    member. The Dockerfile in the same directory is not a member either.
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
    the groups/ directory of this script. The test reads only `dir`. It does
    not look at `renders`, because this check exists to find a group image
    that has no `renders` list. epirhandbook-common, epirhandbook-monolith
    and rbase each build a directory outside groups/. The function skips
    them, and it is correct that they have no `renders`.
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
        # Find repeats in the LIST. A set would hide a repeat.
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
    """Fail if the layout under groups/ and the `renders` lists in
    images.yaml disagree, in EITHER direction, group by group.

    The comparison is per group. A global comparison of stem sets passes when
    the list of a chapter is in the wrong group. A reader is least likely to
    see that error.

    It finds these errors:
      - a group directory that no image builds, or a group directory that an
        image names and that does not exist.
      - a chapter that an image renders, with no package list in the
        directory of that image. Without this check, the chapter drops out
        of the product and nothing reports it.
      - a package list in a group directory for a chapter that the image of
        that group does not render. The cause is a wrong stem, a stale file,
        or a chapter in the wrong group.
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
    """The full package list of one chapter: bare package names, one per
    line, with no comments and no blank lines. All 50 files have this form.

    An EMPTY file is valid. Today only `errors` has one, because that chapter
    runs no R and needs nothing beyond `common`.
    """
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def build(layout):
    """The layout -> {output relative path: [sorted package names], ...} for
    all 7 outputs (6 groups + monolith). The function writes no files. The
    write path and --check both use it, so --check always compares against
    the output that a real run makes."""
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
    """Compare the new `outputs` with the COMMITTED files on disk.

    Returns a list of (relative_path, unified_diff_text), one for each path
    that differs. This includes a wanted file that is missing on disk. It
    also includes a committed file under groups/ that `outputs` does not
    want: a stale list from a group that no longer exists. An empty list
    means that no file differs."""
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

    # Check membership first, in both modes. A layout that disagrees with
    # images.yaml MUST stop the run before the script builds a union, because
    # a union can hide the disagreement. A chapter that needs nothing beyond
    # common, such as `errors`, changes no group list.
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
