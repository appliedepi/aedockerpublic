#!/usr/bin/env python3
"""Unit tests for plan.py -- the CI planner. Run directly:
    python3 .github/scripts/test_plan.py
Wired into build.yml as a guard step that runs BEFORE the real plan is
computed, so a broken planner fails loudly instead of silently misplanning
a real build.
"""
import os
import sys
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

# A synthetic 3-image chain with a frozen (live: false) leaf, used for the
# live-skip and frozen-image tests the 2-image real catalog can't exercise
# on its own.
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


class RequiredCases(unittest.TestCase):
    """The 5 cases named explicitly in the Phase 4 brief."""

    def test_1_rbase_change_cascades_to_epirhandbook(self):
        r = plan.build_plan(CATALOG, changed_files=["rbase/4.3.2/Dockerfile"])
        self.assertEqual(names(r), {"rbase", "epirhandbook"})
        self.assertEqual(r["trigger"], "selective")
        self.assertEqual(r["layers"][0][0]["name"], "rbase")
        self.assertEqual(r["layers"][1][0]["name"], "epirhandbook")
        # base was rebuilt in this same run -> re-resolve its digest live
        self.assertTrue(r["layers"][1][0]["base_freshly_built"])

    def test_2_epirhandbook_change_does_not_rebuild_rbase(self):
        r = plan.build_plan(CATALOG, changed_files=["epirhandbook/2.5/pak_install.R"])
        self.assertEqual(names(r), {"epirhandbook"})
        self.assertNotIn("rbase", names(r))
        self.assertEqual(r["trigger"], "selective")
        # base was NOT rebuilt this run -> must use the recorded pin
        self.assertFalse(r["layers"][0][0]["base_freshly_built"])

    def test_3_images_yaml_change_rebuilds_all_live(self):
        r = plan.build_plan(CATALOG, changed_files=["images.yaml"])
        self.assertEqual(names(r), {"rbase", "epirhandbook"})
        self.assertEqual(r["trigger"], "special")

    def test_4_unrelated_file_selects_nothing(self):
        r = plan.build_plan(CATALOG, changed_files=["README.md", "LICENSE"])
        self.assertEqual(names(r), set())
        self.assertEqual(r["num_layers"], 0)
        self.assertEqual(r["trigger"], "none")

    def test_5_nightly_skips_live_false(self):
        r = plan.build_plan(CHAIN, nightly=True)
        self.assertEqual(names(r), {"rbase", "epirhandbook"})
        self.assertNotIn("epirhandbook_old", names(r))
        self.assertEqual(r["trigger"], "nightly")


class ExtraCases(unittest.TestCase):
    """Beyond the 5 required cases: the subtler design decisions (frozen-image
    semantics, workflow-file trigger, multi-level cascade) pinned down
    explicitly so a future change can't silently regress the reasoning."""

    def test_workflow_file_change_is_also_a_special_trigger(self):
        r = plan.build_plan(CATALOG, changed_files=[".github/workflows/build.yml"])
        self.assertEqual(names(r), {"rbase", "epirhandbook"})
        self.assertEqual(r["trigger"], "special")

    def test_planner_script_change_is_also_a_special_trigger(self):
        # Deliberate extension beyond the brief's literal "images.yaml or a
        # workflow file": a bug in the planner itself is exactly as
        # dangerous and deserves the same blanket revalidation.
        r = plan.build_plan(CATALOG, changed_files=[".github/scripts/plan.py"])
        self.assertEqual(r["trigger"], "special")

    def test_frozen_image_is_not_swept_in_by_a_base_cascade(self):
        # epirhandbook_old is live:false. rbase changing must NOT drag it in
        # via cascade -- freezing means "nothing rebuilds you automatically",
        # and a cascade IS automatic.
        r = plan.build_plan(CHAIN, changed_files=["rbase/4.3.2/Dockerfile"])
        self.assertEqual(names(r), {"rbase", "epirhandbook"})
        self.assertNotIn("epirhandbook_old", names(r))

    def test_frozen_image_still_builds_on_a_direct_edit_to_its_own_files(self):
        # A human explicitly editing a frozen image's own directory is not
        # an automatic rebuild -- it must still build.
        r = plan.build_plan(CHAIN, changed_files=["epirhandbook/2.4/Dockerfile"])
        self.assertIn("epirhandbook_old", names(r))
        self.assertNotIn("rbase", names(r))  # no edge points from rbase to it

    def test_images_yaml_special_case_still_respects_live_false(self):
        r = plan.build_plan(CHAIN, changed_files=["images.yaml"])
        self.assertEqual(names(r), {"rbase", "epirhandbook"})
        self.assertNotIn("epirhandbook_old", names(r))

    def test_multi_file_diff_unions_correctly(self):
        r = plan.build_plan(
            CATALOG,
            changed_files=["epirhandbook/2.5/Dockerfile", "README.md", "rbase/4.3.2/Dockerfile"],
        )
        self.assertEqual(names(r), {"rbase", "epirhandbook"})

    def test_dir_prefix_does_not_false_match_a_sibling_directory(self):
        # epirhandbook/2.5-other/... must NOT match dir "epirhandbook/2.5"
        r = plan.build_plan(CATALOG, changed_files=["epirhandbook/2.5-other/x.txt"])
        self.assertEqual(names(r), set())

    def test_cycle_raises(self):
        cyclic = [
            {"name": "a", "dir": "a", "tags": ["1"], "base": "b:1", "base_digest": None, "live": True},
            {"name": "b", "dir": "b", "tags": ["1"], "base": "a:1", "base_digest": None, "live": True},
        ]
        with self.assertRaises(ValueError):
            plan.build_plan(cyclic, changed_files=["a/x"])

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
            plan.build_plan(typo_catalog, changed_files=["images.yaml"])
        # The error must name both the offending image and the bad base, so
        # an operator can find and fix the typo without re-deriving it.
        self.assertIn("epirhandbook", str(ctx.exception))
        self.assertIn("rbse", str(ctx.exception))

    def test_catalog_deeper_than_max_layers_is_a_hard_error(self):
        # build.yml/nightly.yml only wire up build-layer-0..3 (4 layers).
        # A catalog needing a 5th layer must fail loudly, not silently
        # publish only its first 4 layers (finding 7) -- invisible today
        # with 2 images, but Phase 5a adds ~50 chapter images.
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
            plan.build_plan(deep_chain, nightly=True)
        self.assertIn(str(plan.MAX_SUPPORTED_LAYERS), str(ctx.exception))


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
        # The exact typo from the brief: 'froze' instead of 'frozen'.
        with self.assertRaises(ValueError) as ctx:
            self._validate(self.VALID + "    froze: true\n")
        self.assertIn("froze", str(ctx.exception))

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

    # --- live/frozen: must be a REAL bool, not a string that looks like one -

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

    def test_frozen_must_also_be_a_real_bool(self):
        # Same rule as 'live', applied to 'frozen' -- both are truth-tested
        # downstream by build_plan()/build_image.sh.
        text = self.VALID.rstrip("\n") + '\n    frozen: "false"\n'
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("frozen", str(ctx.exception))

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


class TestAgainstRealCatalog(unittest.TestCase):
    """Canary: the real images.yaml still has the shape the tests above
    assume (2 images, epirhandbook FROM rbase:4.3.2, both live)."""

    def test_real_images_yaml_matches_assumed_shape(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        images_yaml = os.path.join(repo_root, "images.yaml")
        if not os.path.exists(images_yaml):
            self.skipTest(f"images.yaml not found at {images_yaml}")
        images = plan.load_images(images_yaml)
        by_name = {img["name"]: img for img in images}
        self.assertEqual(set(by_name), {"rbase", "epirhandbook"})
        self.assertIsNone(by_name["rbase"]["base"])
        self.assertEqual(by_name["epirhandbook"]["base"], "rbase:4.3.2")
        self.assertTrue(by_name["rbase"]["live"])
        self.assertTrue(by_name["epirhandbook"]["live"])
        # Both are frozen (blocker 2): this project's whole premise is that
        # this exact stack never moves once it reproduces the target render.
        self.assertTrue(by_name["rbase"]["frozen"])
        self.assertTrue(by_name["epirhandbook"]["frozen"])


if __name__ == "__main__":
    unittest.main()
