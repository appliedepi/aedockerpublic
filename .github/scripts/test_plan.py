#!/usr/bin/env python3
"""Unit tests for plan.py -- the CI planner. Run directly:
    python3 .github/scripts/test_plan.py
Wired into build.yml as a guard step that runs BEFORE the real plan is
computed, so a broken planner fails loudly instead of silently misplanning
a real build.
"""
import os
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # noqa: E402

# Mirrors the real images.yaml's `images:` list (2 images, 1 edge). Kept as
# a literal here (not loaded from the file) so these tests exercise
# plan.py's logic in isolation -- see TestAgainstRealCatalog below for the
# check that the real file still matches this shape.
CATALOG = [
    {"name": "rbase", "dir": "rbase/4.3.2", "tags": ["4.3.2"], "base": None,
     "base_digest": None, "live": True},
    {"name": "epirhandbook", "dir": "epirhandbook/2.5", "tags": ["2.5"],
     "base": "rbase:4.3.2", "base_digest": "sha256:aaaa", "live": True},
]

# A synthetic 3-image chain with a not-live (live: false) leaf, used for the
# cascade-exclusion tests the 2-image real catalog can't exercise on its own.
CHAIN = [
    {"name": "rbase", "dir": "rbase/4.3.2", "tags": ["4.3.2"], "base": None,
     "base_digest": None, "live": True},
    {"name": "epirhandbook", "dir": "epirhandbook/2.5", "tags": ["2.5"],
     "base": "rbase:4.3.2", "base_digest": "sha256:aaaa", "live": True},
    {"name": "epirhandbook_old", "dir": "epirhandbook/2.4", "tags": ["2.4"],
     "base": "rbase:4.3.2", "base_digest": "sha256:bbbb", "live": False},
]


def names(result):
    return set(result["image_names"])


class ChangedImageAndCascadeCases(unittest.TestCase):
    """Core selective-build + cascade behavior. plan.py no longer matches
    raw file paths at all -- it is fed an already-resolved list of changed
    image NAMES (--changed-image, one per name; the output of
    changed_images.py in production) and only ever does two pure things
    with it: seed direct selection, then cascade. See build_plan()'s
    docstring."""

    def test_changed_base_cascades_to_its_dependent(self):
        r = plan.build_plan(CATALOG, changed_images=["rbase"])
        self.assertEqual(names(r), {"rbase", "epirhandbook"})
        self.assertEqual(r["trigger"], "selective")
        self.assertEqual(r["layers"][0][0]["name"], "rbase")
        self.assertEqual(r["layers"][1][0]["name"], "epirhandbook")
        # base was rebuilt in this same run -> re-resolve its digest live
        self.assertTrue(r["layers"][1][0]["base_freshly_built"])

    def test_changed_dependent_does_not_rebuild_its_base(self):
        r = plan.build_plan(CATALOG, changed_images=["epirhandbook"])
        self.assertEqual(names(r), {"epirhandbook"})
        self.assertNotIn("rbase", names(r))
        self.assertEqual(r["trigger"], "selective")
        # base was NOT rebuilt this run -> must use the recorded pin
        self.assertFalse(r["layers"][0][0]["base_freshly_built"])

    def test_no_changed_images_selects_nothing(self):
        r = plan.build_plan(CATALOG, changed_images=[])
        self.assertEqual(names(r), set())
        self.assertEqual(r["num_layers"], 0)
        self.assertEqual(r["trigger"], "none")

    def test_omitting_changed_images_entirely_also_selects_nothing(self):
        r = plan.build_plan(CATALOG)
        self.assertEqual(names(r), set())
        self.assertEqual(r["trigger"], "none")

    def test_unknown_changed_image_name_is_a_hard_error(self):
        # changed_images.py should never emit a name outside the catalog,
        # but if it (or a hand-typed --changed-image) ever does, this must
        # be a loud failure -- the same class of mistake as a typo'd
        # `base:` reference (test_unknown_base_name_is_a_hard_error below).
        with self.assertRaises(ValueError) as ctx:
            plan.build_plan(CATALOG, changed_images=["nonexistent-image"])
        self.assertIn("nonexistent-image", str(ctx.exception))

    def test_multiple_changed_images_union_correctly(self):
        r = plan.build_plan(CATALOG, changed_images=["rbase", "epirhandbook"])
        self.assertEqual(names(r), {"rbase", "epirhandbook"})

    def test_not_live_image_is_not_swept_in_by_a_base_cascade(self):
        # epirhandbook_old is live:false. rbase changing must NOT drag it in
        # via cascade -- live:false means "nothing rebuilds you
        # automatically via cascade", and a cascade IS automatic.
        r = plan.build_plan(CHAIN, changed_images=["rbase"])
        self.assertEqual(names(r), {"rbase", "epirhandbook"})
        self.assertNotIn("epirhandbook_old", names(r))

    def test_not_live_image_still_builds_on_a_direct_edit_to_its_own_files(self):
        # A not-live image explicitly named in --changed-image (a direct
        # edit to its own files, as changed_images.py would report) is not
        # an automatic cascade -- it must still build.
        r = plan.build_plan(CHAIN, changed_images=["epirhandbook_old"])
        self.assertIn("epirhandbook_old", names(r))
        self.assertNotIn("rbase", names(r))  # no edge points from rbase to it

    def test_cycle_raises(self):
        cyclic = [
            {"name": "a", "dir": "a", "tags": ["1"], "base": "b:1", "base_digest": None, "live": True},
            {"name": "b", "dir": "b", "tags": ["1"], "base": "a:1", "base_digest": None, "live": True},
        ]
        with self.assertRaises(ValueError):
            plan.build_plan(cyclic)

    def test_unknown_base_name_is_a_hard_error(self):
        # A typo in `base:` ("rbse" instead of "rbase") must be a loud
        # failure, not a silently-dropped cascade edge (finding 6). Before
        # the fix, plan.py's Kahn's-algorithm loop cannot tell "my base was
        # already placed in an earlier layer" apart from "my base was never
        # a real image at all" -- both look like "not in `remaining`" -- so
        # the typo'd image would silently build as if it had no base.
        typo_catalog = [
            {"name": "rbase", "dir": "rbase/4.3.2", "tags": ["4.3.2"], "base": None,
             "base_digest": None, "live": True},
            {"name": "epirhandbook", "dir": "epirhandbook/2.5", "tags": ["2.5"],
             "base": "rbse:4.3.2", "base_digest": "sha256:aaaa", "live": True},  # "rbse" typo
        ]
        with self.assertRaises(ValueError) as ctx:
            plan.build_plan(typo_catalog)
        # The error must name both the offending image and the bad base, so
        # an operator can find and fix the typo without re-deriving it.
        self.assertIn("epirhandbook", str(ctx.exception))
        self.assertIn("rbse", str(ctx.exception))

    def test_catalog_deeper_than_max_layers_is_a_hard_error(self):
        # build.yml only wires up build-layer-0..3 (4 layers). A catalog
        # needing a 5th layer must fail loudly, not silently publish only
        # its first 4 layers (finding 7) -- invisible today with 2 images,
        # but Phase 5a adds ~50 chapter images. This check fires inside
        # topological_order(), which build_plan() calls unconditionally
        # before it ever looks at changed_images -- so no selection is
        # needed to trigger it.
        deep_chain = []
        prev = None
        for i in range(plan.MAX_SUPPORTED_LAYERS + 1):  # 5 layers when the ceiling is 4
            name = f"img{i}"
            deep_chain.append({
                "name": name,
                "dir": name,
                "tags": ["1"],
                "base": f"{prev}:1" if prev else None,
                "base_digest": None,
                "live": True,
            })
            prev = name
        with self.assertRaises(ValueError) as ctx:
            plan.build_plan(deep_chain)
        self.assertIn(str(plan.MAX_SUPPORTED_LAYERS), str(ctx.exception))


class TestMatchingDir(unittest.TestCase):
    """plan.matching_dir() directly -- plan.py still owns this function
    (changed_images.py imports and reuses it rather than re-deriving it;
    see that module's header), so its own invariants are pinned here
    independent of any consumer."""

    def test_exact_dir_match(self):
        self.assertTrue(plan.matching_dir("rbase/4.3.2", "rbase/4.3.2"))

    def test_file_under_dir_matches(self):
        self.assertTrue(plan.matching_dir("rbase/4.3.2/Dockerfile", "rbase/4.3.2"))

    def test_sibling_directory_prefix_does_not_false_match(self):
        # epirhandbook/2.5-other/... must NOT match dir "epirhandbook/2.5"
        self.assertFalse(plan.matching_dir("epirhandbook/2.5-other/x.txt", "epirhandbook/2.5"))

    def test_unrelated_path_does_not_match(self):
        self.assertFalse(plan.matching_dir("README.md", "epirhandbook/2.5"))


class TestValidateCatalog(unittest.TestCase):
    """Direct unit coverage of plan.validate_catalog() -- the strict
    allowlist schema that now sits on top of real, hash-pinned PyYAML
    (Phase 4: minimal_yaml.py deleted after three further rounds of
    adversarial-review blockers for silently diverging from real YAML
    semantics -- four rounds total spent on this question, counting the
    original decision to vendor it. See plan.py's module docstring and
    PROJECT.md section 8.9). Each test drives a real YAML string through
    yaml.safe_load() and then the validator, exactly as plan.load_images()
    does -- never the schema function in isolation on a hand-built dict."""

    # An otherwise-valid one-image catalog. Each test below changes exactly
    # ONE line of it, so a failure can only be attributed to the one field
    # the test means to break.
    VALID = (
        "images:\n"
        "  - name: x\n"
        "    dir: x\n"
        '    tags: ["1"]\n'
        "    base: null\n"
        "    base_digest: null\n"
        "    live: true\n"
    )

    def _validate(self, text):
        return plan.validate_catalog(yaml.safe_load(text), "<test>")

    def test_valid_catalog_passes(self):
        images = self._validate(self.VALID)
        self.assertEqual(images[0]["name"], "x")
        self.assertIs(images[0]["live"], True)
        self.assertIsNone(images[0]["base_digest"])

    # --- unknown / missing keys -----------------------------------------

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate(self.VALID + "    nonexistent_key: true\n")
        self.assertIn("nonexistent_key", str(ctx.exception))

    def test_frozen_key_is_now_rejected_as_unknown(self):
        # `frozen:` was a real catalog field; it no longer exists. Using it
        # must now be a hard "unknown key" error, the same as any other
        # unrecognized field -- this pins the removal itself.
        with self.assertRaises(ValueError) as ctx:
            self._validate(self.VALID + "    frozen: true\n")
        self.assertIn("frozen", str(ctx.exception))
        self.assertNotIn("frozen", sorted(plan.ALLOWED_IMAGE_KEYS))

    def test_missing_required_key_is_rejected(self):
        # 'dir' omitted entirely.
        text = (
            "images:\n"
            "  - name: x\n"
            '    tags: ["1"]\n'
            "    base: null\n"
            "    base_digest: null\n"
            "    live: true\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("dir", str(ctx.exception))

    # --- live: must be a REAL bool, not a string that looks like one -----

    def test_quoted_true_string_is_rejected_for_live(self):
        # live: "true" loads as the STRING "true", not a bool.
        text = self.VALID.replace("live: true", 'live: "true"')
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("live", str(ctx.exception))

    def test_bare_true_is_accepted_as_real_bool(self):
        images = self._validate(self.VALID)
        self.assertIs(images[0]["live"], True)

    def test_bare_no_is_accepted_as_real_bool(self):
        # PyYAML's SafeLoader already turns the bare YAML boolean alias `no`
        # into real Python False -- that is correct YAML and must pass.
        text = self.VALID.replace("live: true", "live: no")
        images = self._validate(text)
        self.assertIs(images[0]["live"], False)

    # --- tags: every element must be a non-empty string ------------------

    def test_unquoted_date_tag_is_rejected(self):
        # tags: [2024-01-01] -- PyYAML resolves the unquoted scalar to a
        # datetime.date, not a string. This is exactly what a hand-rolled
        # reader would have to special-case; the schema catches it for free
        # by simply requiring str.
        text = self.VALID.replace('tags: ["1"]', "tags: [2024-01-01]")
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("tags", str(ctx.exception))

    def test_quoted_string_tag_is_accepted(self):
        text = self.VALID.replace('tags: ["1"]', 'tags: ["2.5"]')
        images = self._validate(text)
        self.assertEqual(images[0]["tags"], ["2.5"])

    def test_unquoted_float_tag_is_rejected(self):
        # tags: [2.5] -- PyYAML resolves this to the float 2.5, not a string.
        text = self.VALID.replace('tags: ["1"]', "tags: [2.5]")
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("tags", str(ctx.exception))

    # --- base_digest: null, or EXACTLY sha256:<64 lowercase hex> ---------

    def test_short_base_digest_is_rejected(self):
        text = self.VALID.replace("base_digest: null", "base_digest: sha256:abc")
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("base_digest", str(ctx.exception))

    def test_real_64_hex_digest_is_accepted(self):
        digest = "sha256:" + "a" * 64
        # A digest requires a base to pin (round-6 rule), so supply one too.
        text = self.VALID.replace("base: null", 'base: "rbase:4.3.2"').replace(
            "base_digest: null", f"base_digest: {digest}"
        )
        images = self._validate(text)
        self.assertEqual(images[0]["base_digest"], digest)

    def test_null_base_digest_is_accepted(self):
        images = self._validate(self.VALID)
        self.assertIsNone(images[0]["base_digest"])

    # --- name / dir -------------------------------------------------------

    def test_bad_name_is_rejected(self):
        text = self.VALID.replace("name: x", 'name: "Bad Name!"')
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("name", str(ctx.exception))

    def test_dir_with_dotdot_is_rejected(self):
        text = self.VALID.replace("dir: x", "dir: a/../etc")
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("dir", str(ctx.exception))

    def test_dir_with_leading_dotslash_is_rejected(self):
        # The round-7 case: `./rbase/4.3.2` is relative and has no '..', so the
        # old check passed it -- but matching_dir compares raw strings, so a
        # changed file `rbase/4.3.2/Dockerfile` would NEVER match it, silently
        # skipping the rebuild. The canonical-form check rejects it.
        text = self.VALID.replace("dir: x", "dir: ./x")
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("dir", str(ctx.exception))

    def test_dir_with_trailing_slash_is_rejected(self):
        text = self.VALID.replace("dir: x", "dir: x/")
        with self.assertRaises(ValueError):
            self._validate(text)

    def test_dir_with_double_slash_is_rejected(self):
        text = self.VALID.replace("dir: x", "dir: a//b")
        with self.assertRaises(ValueError):
            self._validate(text)

    def test_canonical_nested_dir_is_accepted_and_matches(self):
        # A canonical dir validates AND matching_dir finds a file under it --
        # the two must agree, which is the whole point of the canonical rule.
        text = self.VALID.replace("dir: x", "dir: rbase/4.3.2")
        images = self._validate(text)
        self.assertEqual(images[0]["dir"], "rbase/4.3.2")
        self.assertTrue(plan.matching_dir("rbase/4.3.2/Dockerfile", "rbase/4.3.2"))

    # --- a couple of extra rules from validate_catalog's own contract ----

    def test_top_level_extra_key_is_rejected(self):
        text = self.VALID + "extra: true\n"
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("images", str(ctx.exception))

    # --- round-6 review: malformed field values reaching the publish plan --

    def test_tag_with_a_comma_is_rejected(self):
        # tags are join(',')'d and split(',') back downstream, so a comma in a
        # tag would silently become TWO published tags. Must be rejected here.
        text = self.VALID.replace('tags: ["1"]', 'tags: ["prod,latest"]')
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("tags", str(ctx.exception))

    def test_tag_with_a_slash_is_rejected(self):
        text = self.VALID.replace('tags: ["1"]', 'tags: ["a/b"]')
        with self.assertRaises(ValueError):
            self._validate(text)

    def test_base_with_empty_tag_is_rejected(self):
        # base: "rbase:" -- a bare name with no tag would reach the build with
        # an empty base tag.
        text = self.VALID.replace("base: null", 'base: "rbase:"')
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("base", str(ctx.exception))

    def test_valid_base_reference_is_accepted(self):
        text = self.VALID.replace("base: null", 'base: "rbase:4.3.2"')
        images = self._validate(text)
        self.assertEqual(images[0]["base"], "rbase:4.3.2")

    def test_base_digest_without_a_base_is_rejected(self):
        # A digest pin for a null base is meaningless and would be silently
        # ignored -- reject it so it can't masquerade as an active pin.
        text = self.VALID.replace(
            "base_digest: null", "base_digest: sha256:" + "a" * 64
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("base", str(ctx.exception).lower())

    def test_renders_qmd_is_accepted_and_stem_must_match_dir_basename(self):
        # The per-chapter split images STATE the .qmd they render. The stem is
        # validated against the dir basename so the stated source cannot drift
        # from the build context it belongs to. Note the image name is
        # lowercased (Docker) while the source keeps its real case.
        text = (
            "images:\n"
            "  - name: epirhandbook-transition_to_r\n"
            "    renders: new_pages/transition_to_R.qmd\n"
            "    dir: epirhandbook/2.6/chapters/transition_to_R\n"
            '    tags: ["2.6"]\n'
            "    base: null\n    base_digest: null\n"
        )
        images = self._validate(text)
        self.assertEqual(images[0]["renders"], "new_pages/transition_to_R.qmd")

    def test_index_renders_root_qmd_not_new_pages(self):
        # index.qmd lives at the source ROOT, not under new_pages/ -- the very
        # exception that makes `source` worth stating rather than deriving.
        text = (
            "images:\n"
            "  - name: epirhandbook-index\n"
            "    renders: index.qmd\n"
            "    dir: epirhandbook/2.6/chapters/index\n"
            '    tags: ["2.6"]\n'
            "    base: null\n    base_digest: null\n"
        )
        images = self._validate(text)
        self.assertEqual(images[0]["renders"], "index.qmd")

    def test_renders_disagreeing_with_dir_basename_is_rejected(self):
        text = (
            "images:\n"
            "  - name: epirhandbook-transition_to_r\n"
            "    renders: new_pages/basics.qmd\n"
            "    dir: epirhandbook/2.6/chapters/transition_to_R\n"
            '    tags: ["2.6"]\n'
            "    base: null\n    base_digest: null\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("renders", str(ctx.exception))

    def test_name_must_identify_the_chapter_it_renders(self):
        # A row that renders basics.qmd but publishes as epirhandbook-cleaning
        # would put a LYING name on a public registry. source-vs-dir agreement
        # alone does not catch it.
        text = (
            "images:\n"
            "  - name: epirhandbook-cleaning\n"
            "    renders: new_pages/basics.qmd\n"
            "    dir: epirhandbook/2.6/chapters/basics\n"
            '    tags: ["2.6"]\n'
            "    base: null\n    base_digest: null\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("name", str(ctx.exception))

    def test_lowercased_name_for_uppercase_chapter_is_accepted(self):
        # Docker forces lowercase; the name still has to identify the chapter.
        text = (
            "images:\n"
            "  - name: epirhandbook-transition_to_r\n"
            "    renders: new_pages/transition_to_R.qmd\n"
            "    dir: epirhandbook/2.6/chapters/transition_to_R\n"
            '    tags: ["2.6"]\n'
            "    base: null\n    base_digest: null\n"
        )
        self.assertEqual(len(self._validate(text)), 1)

    def test_renders_must_be_a_qmd(self):
        text = (
            "images:\n"
            "  - name: epirhandbook-basics\n"
            "    renders: new_pages/basics.Rmd\n"
            "    dir: epirhandbook/2.6/chapters/basics\n"
            '    tags: ["2.6"]\n'
            "    base: null\n    base_digest: null\n"
        )
        with self.assertRaises(ValueError):
            self._validate(text)

    def test_duplicate_image_names_are_rejected(self):
        # Every downstream structure keys by name and would keep only the last
        # duplicate; a change under the first would plan the second's dir/tags.
        text = (
            "images:\n"
            '  - name: dup\n    dir: a\n    tags: ["1"]\n    base: null\n    base_digest: null\n'
            '  - name: dup\n    dir: b\n    tags: ["2"]\n    base: null\n    base_digest: null\n'
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("duplicate", str(ctx.exception).lower())


class TestMergedCatalogs(unittest.TestCase):
    """The catalog is split across files by OWNERSHIP (hand-maintained root vs
    generated per-phase), but base edges cross the files -- epirhandbook-common
    is FROM rbase. The planner must see them merged, or `rbase` looks like a
    typo and the whole plan dies. This is the failure an earlier schema-only
    check missed: validate_catalog passed on the 2.6 file alone while the real
    planner (build_plan) raised."""

    def _write(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    ROOT = (
        "images:\n"
        "  - name: rbase\n    dir: rbase/4.3.2\n"
        '    tags: ["4.3.2"]\n    base: null\n    base_digest: null\n'
    )
    SPLIT = (
        "images:\n"
        "  - name: epirhandbook-common\n    dir: epirhandbook/2.6/common\n"
        '    tags: ["2.6"]\n    base: "rbase:4.3.2"\n    base_digest: null\n'
    )

    def test_cross_file_base_edge_resolves_when_merged(self):
        root, split = self._write(self.ROOT), self._write(self.SPLIT)
        images = plan.load_catalogs([root, split])
        self.assertEqual(len(images), 2)
        # The real boundary: build_plan (not just the schema check) must
        # work, AND the cascade must cross the file boundary: rbase changing
        # must reach epirhandbook-common, defined in the OTHER file.
        r = plan.build_plan(images, changed_images=["rbase"])
        self.assertEqual(names(r), {"rbase", "epirhandbook-common"})
        self.assertEqual(r["layers"][0][0]["name"], "rbase")

    def test_split_catalog_alone_is_rejected_by_the_planner(self):
        # Loading only the generated half leaves the base dangling. This
        # fires inside topological_order(), before build_plan() ever looks
        # at changed_images, so no selection argument is needed to trigger it.
        split = self._write(self.SPLIT)
        with self.assertRaises(ValueError) as ctx:
            plan.build_plan(plan.load_catalogs([split]))
        self.assertIn("rbase", str(ctx.exception))

    def test_same_name_in_two_catalogs_is_rejected(self):
        a, b = self._write(self.ROOT), self._write(self.ROOT)
        with self.assertRaises(ValueError) as ctx:
            plan.load_catalogs([a, b])
        self.assertIn("already defined", str(ctx.exception))


class TestAgainstRealCatalog(unittest.TestCase):
    """Canary: the real catalogs still have the shape the tests above assume.
    The public deliverable is now the 2.7 catalog only (2.5/2.6 removed from
    the published set -- their directories stay on disk as provenance, but
    the CI planner no longer loads their catalog entries): the root
    images.yaml holds just the 2.7 base image (rbase:4.6.0-2026-07-01), and
    per-chapter split lives in epirhandbook/2.7/images.yaml, FROM this rbase
    across the file boundary."""

    def _real_catalog_paths(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        root_yaml = os.path.join(repo_root, "images.yaml")
        split_yaml = os.path.join(repo_root, "epirhandbook", "2.7", "images.yaml")
        return root_yaml, split_yaml

    def test_real_images_yaml_matches_assumed_shape(self):
        root_yaml, _ = self._real_catalog_paths()
        if not os.path.exists(root_yaml):
            self.skipTest(f"images.yaml not found at {root_yaml}")
        images = plan.load_images(root_yaml)
        by_name = {img["name"]: img for img in images}
        self.assertEqual(set(by_name), {"rbase"})
        self.assertIsNone(by_name["rbase"]["base"])
        self.assertEqual(by_name["rbase"]["dir"], "rbase/4.6.0")
        self.assertEqual(by_name["rbase"]["tags"], ["4.6.0-2026-07-01"])
        self.assertTrue(by_name["rbase"]["live"])

    def test_real_catalogs_merge_and_plan_2_7_only(self):
        # Exercises the actual production planner invocation (build.yml
        # passes exactly these two real files): confirms the cross-file base
        # edge (epirhandbook-common:2.7 FROM rbase:4.6.0-2026-07-01) resolves
        # without error, and that no 2.5/2.6/4.3.2 artifact survives in the
        # merged plan. `changed_images` lists every real name directly (no
        # nightly/"select everything" mode exists any more) to force full
        # selection for this shape check.
        root_yaml, split_yaml = self._real_catalog_paths()
        if not os.path.exists(root_yaml) or not os.path.exists(split_yaml):
            self.skipTest("real catalog files not found")
        images = plan.load_catalogs([root_yaml, split_yaml])
        r = plan.build_plan(images, changed_images=[img["name"] for img in images])
        image_names = names(r)
        self.assertIn("rbase", image_names)
        self.assertIn("epirhandbook-common", image_names)
        self.assertEqual(len(image_names), 51)  # rbase + common + 49 chapters
        self.assertNotIn("epirhandbook", image_names)  # the old 2.5 monolith name
        by_name = {img["name"]: img for layer in r["layers"] for img in layer}
        self.assertEqual(by_name["rbase"]["tags"], ["4.6.0-2026-07-01"])
        for name, img in by_name.items():
            self.assertNotIn("2.5", img["tags"])
            self.assertNotIn("2.6", img["tags"])
            self.assertNotIn("4.3.2", img["tags"])
        self.assertEqual(r["layers"][0][0]["name"], "rbase")  # base-most first

    def test_common_change_cascades_to_every_chapter_but_not_rbase(self):
        # Discriminator (a): a change to common's dir must plan common +
        # all 49 chapters (the cascade), but NOT rbase -- the cascade only
        # flows base -> dependent, never upstream.
        root_yaml, split_yaml = self._real_catalog_paths()
        if not os.path.exists(root_yaml) or not os.path.exists(split_yaml):
            self.skipTest("real catalog files not found")
        images = plan.load_catalogs([root_yaml, split_yaml])
        r = plan.build_plan(images, changed_images=["epirhandbook-common"])
        image_names = names(r)
        self.assertEqual(len(image_names), 50)  # common + 49 chapters
        self.assertIn("epirhandbook-common", image_names)
        self.assertNotIn("rbase", image_names)

    def test_single_chapter_change_selects_only_that_chapter(self):
        # Discriminator (b): a change to one chapter selects ONLY that
        # chapter -- no cascade (nothing in this catalog is FROM a chapter),
        # and no fan-out to common or rbase.
        root_yaml, split_yaml = self._real_catalog_paths()
        if not os.path.exists(root_yaml) or not os.path.exists(split_yaml):
            self.skipTest("real catalog files not found")
        images = plan.load_catalogs([root_yaml, split_yaml])
        r = plan.build_plan(images, changed_images=["epirhandbook-basics"])
        self.assertEqual(names(r), {"epirhandbook-basics"})

    def test_unchanged_real_catalog_selects_nothing(self):
        # Discriminator (d), the plan.py half: an empty --changed-image list
        # (every image unchanged since its published revision, as
        # changed_images.py would report) plans nothing at all.
        root_yaml, split_yaml = self._real_catalog_paths()
        if not os.path.exists(root_yaml) or not os.path.exists(split_yaml):
            self.skipTest("real catalog files not found")
        images = plan.load_catalogs([root_yaml, split_yaml])
        r = plan.build_plan(images, changed_images=[])
        self.assertEqual(names(r), set())
        self.assertEqual(r["trigger"], "none")


class TestBuildContextAndChapterRenders(unittest.TestCase):
    """Round-2 review: `dir` was used as the docker build CONTEXT, but a 2.6
    chapter's Dockerfile COPYs from epirhandbook/2.6, not from the chapter
    directory -- so CI planned the images then died at `docker build`
    ('/pak_install_subset.R': not found). `context` separates the two facts:
    dir = this image's own files (change scope + Dockerfile location),
    context = the root COPY resolves against."""

    def _validate(self, text):
        return plan.validate_catalog(yaml.safe_load(text), "<test>")

    ROW = (
        "images:\n"
        "  - name: epirhandbook-basics\n"
        "    renders: new_pages/basics.qmd\n"
        "    dir: epirhandbook/2.6/chapters/basics\n"
        "    context: epirhandbook/2.6\n"
        '    tags: ["2.6"]\n'
        "    base: null\n    base_digest: null\n"
    )

    def test_context_is_accepted_and_reaches_the_plan(self):
        imgs = self._validate(self.ROW)
        self.assertEqual(imgs[0]["context"], "epirhandbook/2.6")
        r = plan.build_plan(imgs, changed_images=["epirhandbook-basics"])
        self.assertEqual(r["layers"][0][0]["context"], "epirhandbook/2.6")

    def test_context_defaults_to_dir_when_absent(self):
        # rbase / the 2.5 monolith: the Dockerfile sits in its own context.
        text = (
            "images:\n  - name: rbase\n    dir: rbase/4.3.2\n"
            '    tags: ["4.3.2"]\n    base: null\n    base_digest: null\n'
        )
        r = plan.build_plan(self._validate(text), changed_images=["rbase"])
        self.assertEqual(r["layers"][0][0]["context"], "rbase/4.3.2")

    def test_dir_outside_context_is_rejected(self):
        text = self.ROW.replace("context: epirhandbook/2.6", "context: rbase/4.3.2")
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("context", str(ctx.exception))

    def test_chapter_image_without_renders_is_rejected(self):
        text = self.ROW.replace("    renders: new_pages/basics.qmd\n", "")
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("renders", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
