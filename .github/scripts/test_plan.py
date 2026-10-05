#!/usr/bin/env python3
"""Unit tests for plan.py, the CI planner. Run directly:
    python3 .github/scripts/test_plan.py
build.yml runs these tests as a guard step before it computes the real plan.
So a broken planner fails with an error and cannot plan a real build wrong.
"""
import os
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # noqa: E402

# A fixture with 2 images and 1 edge, in the shape of the original catalog.
# It is a literal here, not loaded from the file, so these tests check the
# logic of plan.py alone. See TestAgainstRealCatalog below for the canary on
# the real 9-image catalog.
CATALOG = [
    {"name": "rbase", "dir": "rbase/4.3.2", "tags": ["4.3.2"], "base": None,
     "live": True},
    {"name": "epirhandbook", "dir": "epirhandbook/2.5", "tags": ["2.5"],
     "base": "rbase:4.3.2", "live": True},
]

# A synthetic 3-image chain with a not-live (live: false) leaf. The
# cascade-exclusion tests use it, because the 2-image fixture cannot test
# that case.
CHAIN = [
    {"name": "rbase", "dir": "rbase/4.3.2", "tags": ["4.3.2"], "base": None,
     "live": True},
    {"name": "epirhandbook", "dir": "epirhandbook/2.5", "tags": ["2.5"],
     "base": "rbase:4.3.2", "live": True},
    {"name": "epirhandbook_old", "dir": "epirhandbook/2.4", "tags": ["2.4"],
     "base": "rbase:4.3.2", "live": False},
]


def names(result):
    return set(result["image_names"])


class ChangedImageAndCascadeCases(unittest.TestCase):
    """The core selective-build and cascade behaviour. plan.py does not
    match raw file paths. It gets a resolved list of changed image names
    (--changed-image, one per name), which in production is the output of
    changed_images.py. It does two pure things with the list: it fills the
    direct selection, then it cascades. See the docstring of
    build_plan()."""

    def test_changed_base_cascades_to_its_dependent(self):
        r = plan.build_plan(CATALOG, changed_images=["rbase"])
        self.assertEqual(names(r), {"rbase", "epirhandbook"})
        self.assertEqual(r["trigger"], "selective")
        self.assertEqual(r["layers"][0][0]["name"], "rbase")
        self.assertEqual(r["layers"][1][0]["name"], "epirhandbook")
        # This run rebuilt the base -> resolve its digest from the registry
        self.assertTrue(r["layers"][1][0]["base_freshly_built"])

    def test_changed_dependent_does_not_rebuild_its_base(self):
        r = plan.build_plan(CATALOG, changed_images=["epirhandbook"])
        self.assertEqual(names(r), {"epirhandbook"})
        self.assertNotIn("rbase", names(r))
        self.assertEqual(r["trigger"], "selective")
        # This run did not rebuild the base -> resolve the published base tag
        # from the registry. No recorded pin exists, so none is read.
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
        # changed_images.py should never give a name outside the catalog.
        # If it does, or a hand-typed --changed-image does, this MUST fail
        # with an error. It is the same kind of mistake as a typo in a
        # `base:` reference (test_unknown_base_name_is_a_hard_error below).
        with self.assertRaises(ValueError) as ctx:
            plan.build_plan(CATALOG, changed_images=["nonexistent-image"])
        self.assertIn("nonexistent-image", str(ctx.exception))

    def test_multiple_changed_images_union_correctly(self):
        r = plan.build_plan(CATALOG, changed_images=["rbase", "epirhandbook"])
        self.assertEqual(names(r), {"rbase", "epirhandbook"})

    def test_not_live_image_is_not_swept_in_by_a_base_cascade(self):
        # epirhandbook_old is live:false. A change to rbase MUST NOT add
        # it by cascade. live:false means "no cascade rebuilds this image",
        # and a cascade is automatic.
        r = plan.build_plan(CHAIN, changed_images=["rbase"])
        self.assertEqual(names(r), {"rbase", "epirhandbook"})
        self.assertNotIn("epirhandbook_old", names(r))

    def test_not_live_image_still_builds_on_a_direct_edit_to_its_own_files(self):
        # A not-live image named in --changed-image is not an automatic
        # cascade: it is a direct edit to its own files, as
        # changed_images.py reports it. So it MUST still build.
        r = plan.build_plan(CHAIN, changed_images=["epirhandbook_old"])
        self.assertIn("epirhandbook_old", names(r))
        self.assertNotIn("rbase", names(r))  # no edge points from rbase to it

    def test_cycle_raises(self):
        cyclic = [
            {"name": "a", "dir": "a", "tags": ["1"], "base": "b:1", "live": True},
            {"name": "b", "dir": "b", "tags": ["1"], "base": "a:1", "live": True},
        ]
        with self.assertRaises(ValueError):
            plan.build_plan(cyclic)

    def test_unknown_base_name_is_a_hard_error(self):
        # A typo in `base:` ("rbse" instead of "rbase") MUST fail with an
        # error. It MUST NOT drop the cascade edge without one (finding 6).
        # Before the fix, the Kahn's-algorithm loop in plan.py could not
        # tell "an earlier layer holds my base" from "my base is not an
        # image". Both look like "not in `remaining`". So the image with
        # the typo built as if it had no base, with no error.
        typo_catalog = [
            {"name": "rbase", "dir": "rbase/4.3.2", "tags": ["4.3.2"], "base": None,
             "live": True},
            {"name": "epirhandbook", "dir": "epirhandbook/2.5", "tags": ["2.5"],
             "base": "rbse:4.3.2", "live": True},  # "rbse" typo
        ]
        with self.assertRaises(ValueError) as ctx:
            plan.build_plan(typo_catalog)
        # The error MUST name both the image and the bad base, so that an
        # operator can find and fix the typo directly.
        self.assertIn("epirhandbook", str(ctx.exception))
        self.assertIn("rbse", str(ctx.exception))

    def test_catalog_deeper_than_max_layers_is_a_hard_error(self):
        # build.yml has jobs only for build-layer-0..3 (4 layers). A
        # catalog that needs a 5th layer MUST fail with an error. It MUST
        # NOT publish only its first 4 layers (finding 7). The catalog
        # holds 9 images today in 3 layers, so the 4-layer limit leaves one
        # spare. The check is in topological_order(). build_plan() always
        # calls it before it reads changed_images, so the test needs no
        # selection.
        deep_chain = []
        prev = None
        for i in range(plan.MAX_SUPPORTED_LAYERS + 1):  # 5 layers when the ceiling is 4
            name = f"img{i}"
            deep_chain.append({
                "name": name,
                "dir": name,
                "tags": ["1"],
                "base": f"{prev}:1" if prev else None,
                "live": True,
            })
            prev = name
        with self.assertRaises(ValueError) as ctx:
            plan.build_plan(deep_chain)
        self.assertIn(str(plan.MAX_SUPPORTED_LAYERS), str(ctx.exception))


class TestMatchingDir(unittest.TestCase):
    """plan.matching_dir(), tested directly. plan.py owns this function, and
    changed_images.py imports it (see the header of that module). So these
    tests pin its invariants without any consumer."""

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
    """Unit tests for plan.validate_catalog(), the strict allowlist schema
    over real, hash-pinned PyYAML. Phase 4 deleted minimal_yaml.py after
    three more review rounds found blockers where it differed from real
    YAML. Counting the first decision to vendor it, that was four rounds on
    one question. See the module docstring of plan.py and CHANGELOG.md,
    phase 4 log, 8.9. Each test sends a real YAML string through
    yaml.safe_load() and then the validator, as plan.load_images() does. No
    test calls the schema function alone on a hand-built dict."""

    # A valid one-image catalog. Each test below changes one line of it.
    # So a failure can only come from the field that the test breaks.
    VALID = (
        "images:\n"
        "  - name: x\n"
        "    description: a test image\n"
        "    dir: x\n"
        '    tags: ["1"]\n'
        "    base: null\n"
        "    live: true\n"
    )

    def _validate(self, text):
        return plan.validate_catalog(yaml.safe_load(text), "<test>")

    def test_valid_catalog_passes(self):
        images = self._validate(self.VALID)
        self.assertEqual(images[0]["name"], "x")
        self.assertIs(images[0]["live"], True)

    # --- unknown / missing keys -----------------------------------------

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._validate(self.VALID + "    nonexistent_key: true\n")
        self.assertIn("nonexistent_key", str(ctx.exception))

    def test_frozen_key_is_now_rejected_as_unknown(self):
        # `frozen:` was a real catalog field, and it no longer exists. It
        # MUST now give a hard "unknown key" error, like any other unknown
        # field. This pins the removal.
        with self.assertRaises(ValueError) as ctx:
            self._validate(self.VALID + "    frozen: true\n")
        self.assertIn("frozen", str(ctx.exception))
        self.assertNotIn("frozen", sorted(plan.ALLOWED_IMAGE_KEYS))

    def test_base_digest_key_is_now_rejected_as_unknown(self):
        # `base_digest:` was a real catalog field, an optional cross-check on
        # the base's digest. It no longer exists (§8.10). It MUST now give a
        # hard "unknown key" error, like any other unknown field. This pins
        # the removal.
        with self.assertRaises(ValueError) as ctx:
            self._validate(self.VALID + "    base_digest: null\n")
        self.assertIn("base_digest", str(ctx.exception))
        self.assertNotIn("base_digest", sorted(plan.ALLOWED_IMAGE_KEYS))

    def test_missing_required_key_is_rejected(self):
        # 'dir' omitted entirely.
        text = (
            "images:\n"
            "  - name: x\n"
            "    description: a test image\n"
            '    tags: ["1"]\n'
            "    base: null\n"
            "    live: true\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("dir", str(ctx.exception))

    # --- description: REQUIRED, and a non-empty string --------------------
    #
    # build_image.sh stamps this field as the image's
    # org.opencontainers.image.description OCI label. Before the field existed,
    # every published image had the label it inherited from ubuntu. So
    # `docker inspect` showed Canonical's text for this project's images.
    # For that reason the key is REQUIRED. If it were optional, a record
    # without it would publish the inherited description, and nothing would
    # fail.

    def test_description_is_accepted_and_returned_unchanged(self):
        text = self.VALID.replace(
            "description: a test image",
            "description: R environment for the Basics chapters",
        )
        images = self._validate(text)
        self.assertEqual(
            images[0]["description"], "R environment for the Basics chapters"
        )

    def test_missing_description_is_rejected(self):
        # This case is why the key is REQUIRED. A record with no description
        # MUST NOT validate.
        text = self.VALID.replace("    description: a test image\n", "")
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("description", str(ctx.exception))

    def test_empty_description_is_rejected(self):
        text = self.VALID.replace("description: a test image", 'description: ""')
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("description", str(ctx.exception))

    def test_whitespace_only_description_is_rejected(self):
        # A label of three spaces is an empty label.
        text = self.VALID.replace("description: a test image", 'description: "   "')
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("description", str(ctx.exception))

    def test_multi_line_description_is_rejected(self):
        # The catalog header states "One line about the image", and a label
        # is one line. A YAML block scalar is the usual accidental cause: it
        # adds a trailing newline that the author does not see.
        text = self.VALID.replace(
            "    description: a test image\n",
            "    description: |\n      a test image\n      with a second line\n",
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("ONE line", str(ctx.exception))

    def test_single_line_description_with_no_trailing_newline_is_accepted(self):
        # The passing direction. A gate tested only with a bad input never
        # runs its accepting branch.
        images = self._validate(self.VALID)
        self.assertEqual(images[0]["description"], "a test image")

    def test_exotic_line_separators_in_description_are_rejected(self):
        # A newline test for "\n" and "\r" misses five separators. Ordinary
        # double-quoted YAML escapes give them, and Python counts them as
        # line boundaries. Each would reach the registry as a broken
        # description. An adversarial review found this on 2026-09-22.
        for name, escape in (
            ("vertical tab", "\\v"),
            ("form feed", "\\f"),
            ("next line", "\\N"),
            ("line separator", "\\L"),
            ("paragraph separator", "\\P"),
        ):
            with self.subTest(separator=name):
                text = self.VALID.replace(
                    "description: a test image",
                    'description: "a test%simage"' % escape,
                )
                with self.assertRaises(ValueError) as ctx:
                    self._validate(text)
                self.assertIn("ONE line", str(ctx.exception))

    def test_non_string_description_is_rejected(self):
        # PyYAML resolves a bare 2.9 to a float, not a string. The tags tests
        # below cover the same implicit-scalar trap.
        text = self.VALID.replace("description: a test image", "description: 2.9")
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("description", str(ctx.exception))

    def test_description_is_required_not_optional(self):
        # Pins the classification itself.
        # test_missing_description_is_rejected depends on it.
        self.assertIn("description", plan.REQUIRED_IMAGE_KEYS)
        self.assertNotIn("description", plan.OPTIONAL_IMAGE_KEYS)

    # --- live: MUST be a real bool, not a string that looks like one -----

    def test_quoted_true_string_is_rejected_for_live(self):
        # live: "true" loads as the string "true", not a bool.
        text = self.VALID.replace("live: true", 'live: "true"')
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("live", str(ctx.exception))

    def test_bare_true_is_accepted_as_real_bool(self):
        images = self._validate(self.VALID)
        self.assertIs(images[0]["live"], True)

    def test_bare_no_is_accepted_as_real_bool(self):
        # PyYAML's SafeLoader turns the bare YAML boolean alias `no` into
        # Python False. That is correct YAML, and it MUST pass.
        text = self.VALID.replace("live: true", "live: no")
        images = self._validate(text)
        self.assertIs(images[0]["live"], False)

    # --- tags: every element must be a non-empty string ------------------

    def test_unquoted_date_tag_is_rejected(self):
        # tags: [2024-01-01]: PyYAML resolves the unquoted scalar to a
        # datetime.date, not a string. A hand-written reader would need a
        # special case for this. The schema finds it because it needs str.
        text = self.VALID.replace('tags: ["1"]', "tags: [2024-01-01]")
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("tags", str(ctx.exception))

    def test_quoted_string_tag_is_accepted(self):
        text = self.VALID.replace('tags: ["1"]', 'tags: ["2.5"]')
        images = self._validate(text)
        self.assertEqual(images[0]["tags"], ["2.5"])

    def test_unquoted_float_tag_is_rejected(self):
        # tags: [2.5]: PyYAML resolves this to the float 2.5, not a string.
        text = self.VALID.replace('tags: ["1"]', "tags: [2.5]")
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("tags", str(ctx.exception))

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
        # The round 7 case: `./rbase/4.3.2` is relative and has no '..', so the
        # old check passed it. But matching_dir compares raw strings, so the
        # changed file `rbase/4.3.2/Dockerfile` never matches it, and CI skips
        # the rebuild with no error. The canonical-form check rejects it.
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
        # A canonical dir validates, and matching_dir finds a file under it.
        # The canonical rule exists so that these two agree.
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

    # --- round 6 review: malformed field values that reach the publish plan --

    def test_tag_with_a_comma_is_rejected(self):
        # Later steps join tags with ',' and split them again on ','. So a
        # comma in a tag would become two published tags with no error. The
        # validator MUST reject it here.
        text = self.VALID.replace('tags: ["1"]', 'tags: ["prod,latest"]')
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("tags", str(ctx.exception))

    def test_tag_with_a_slash_is_rejected(self):
        text = self.VALID.replace('tags: ["1"]', 'tags: ["a/b"]')
        with self.assertRaises(ValueError):
            self._validate(text)

    def test_base_with_empty_tag_is_rejected(self):
        # base: "rbase:": a bare name with no tag would reach the build with
        # an empty base tag.
        text = self.VALID.replace("base: null", 'base: "rbase:"')
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("base", str(ctx.exception))

    def test_valid_base_reference_is_accepted(self):
        text = self.VALID.replace("base: null", 'base: "rbase:4.3.2"')
        images = self._validate(text)
        self.assertEqual(images[0]["base"], "rbase:4.3.2")

    def test_renders_qmd_is_accepted_and_stem_must_match_dir_basename(self):
        # The string form of `renders` states the one .qmd that an image
        # renders. The validator checks the stem against the dir basename, so
        # the stated source cannot disagree with its build context. No live 2.9
        # image uses this form. The fixture below is a synthetic per-chapter
        # record. The image name is lowercase (Docker), and the source keeps
        # its real case.
        text = (
            "images:\n"
            "  - name: epirhandbook-transition_to_r\n"
            "    description: a test image\n"
            "    renders: new_pages/transition_to_R.qmd\n"
            "    dir: epirhandbook/2.6/chapters/transition_to_R\n"
            '    tags: ["2.6"]\n'
            "    base: null\n"
        )
        images = self._validate(text)
        self.assertEqual(images[0]["renders"], "new_pages/transition_to_R.qmd")

    def test_index_renders_root_qmd_not_new_pages(self):
        # In the 2.6 layout, index.qmd was at the source root, not under
        # new_pages/. This exception is why `renders` is stated and not derived.
        text = (
            "images:\n"
            "  - name: epirhandbook-index\n"
            "    description: a test image\n"
            "    renders: index.qmd\n"
            "    dir: epirhandbook/2.6/chapters/index\n"
            '    tags: ["2.6"]\n'
            "    base: null\n"
        )
        images = self._validate(text)
        self.assertEqual(images[0]["renders"], "index.qmd")

    def test_renders_disagreeing_with_dir_basename_is_rejected(self):
        text = (
            "images:\n"
            "  - name: epirhandbook-transition_to_r\n"
            "    description: a test image\n"
            "    renders: new_pages/basics.qmd\n"
            "    dir: epirhandbook/2.6/chapters/transition_to_R\n"
            '    tags: ["2.6"]\n'
            "    base: null\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("renders", str(ctx.exception))

    def test_name_must_identify_the_chapter_it_renders(self):
        # A row that renders basics.qmd but publishes as epirhandbook-cleaning
        # would put a false name on a public registry. A check of source
        # against dir alone does not find it.
        text = (
            "images:\n"
            "  - name: epirhandbook-cleaning\n"
            "    description: a test image\n"
            "    renders: new_pages/basics.qmd\n"
            "    dir: epirhandbook/2.6/chapters/basics\n"
            '    tags: ["2.6"]\n'
            "    base: null\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("name", str(ctx.exception))

    def test_lowercased_name_for_uppercase_chapter_is_accepted(self):
        # Docker needs lowercase. The name MUST still identify the chapter.
        text = (
            "images:\n"
            "  - name: epirhandbook-transition_to_r\n"
            "    description: a test image\n"
            "    renders: new_pages/transition_to_R.qmd\n"
            "    dir: epirhandbook/2.6/chapters/transition_to_R\n"
            '    tags: ["2.6"]\n'
            "    base: null\n"
        )
        self.assertEqual(len(self._validate(text)), 1)

    def test_renders_must_be_a_qmd(self):
        text = (
            "images:\n"
            "  - name: epirhandbook-basics\n"
            "    description: a test image\n"
            "    renders: new_pages/basics.Rmd\n"
            "    dir: epirhandbook/2.6/chapters/basics\n"
            '    tags: ["2.6"]\n'
            "    base: null\n"
        )
        with self.assertRaises(ValueError):
            self._validate(text)

    # --- Unit F: group images, with `renders` as a list of .qmd files ------
    #
    # Phase 5b merged the 49 single-chapter images into 6 group images. Each
    # group image renders several chapters. So `renders` MUST accept a
    # single .qmd string (unchanged) or a non-empty list of .qmd strings.
    # These fixtures are synthetic. TestAgainstRealCatalog covers the live
    # 2.9 catalog.

    def test_list_form_renders_record_is_accepted(self):
        # Pins acceptance of the list form: validate_catalog returns the
        # `renders` list unchanged, in the order the catalog gives it.
        # The six group images in epirhandbook/2.9/images.yaml all use
        # this form.
        text = (
            "images:\n"
            "  - name: epirhandbook-analysis\n"
            "    description: a test image\n"
            "    renders:\n"
            "      - chapters/regression.qmd\n"
            "      - chapters/stat_tests.qmd\n"
            "    dir: epirhandbook/2.8/groups/analysis\n"
            '    tags: ["2.8"]\n'
            "    base: null\n"
        )
        images = self._validate(text)
        self.assertEqual(
            images[0]["renders"],
            ["chapters/regression.qmd", "chapters/stat_tests.qmd"],
        )

    def test_list_form_renders_rejects_duplicate_qmd_within_one_record(self):
        # Stage 2: the same .qmd twice in one record's `renders` has no
        # meaning, because no single build owns it. The validator MUST reject
        # it.
        text = (
            "images:\n"
            "  - name: epirhandbook-analysis\n"
            "    description: a test image\n"
            "    renders:\n"
            "      - chapters/regression.qmd\n"
            "      - chapters/regression.qmd\n"
            "    dir: epirhandbook/2.8/groups/analysis\n"
            '    tags: ["2.8"]\n'
            "    base: null\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("regression.qmd", str(ctx.exception))

    def test_list_form_renders_requires_name_to_identify_the_group(self):
        # Stage 2: in the list form, `name` MUST identify the group (the dir
        # basename). This matches the string-form chapter check above, so
        # the name cannot give a false account of the content.
        text = (
            "images:\n"
            "  - name: epirhandbook-wrong-group\n"
            "    description: a test image\n"
            "    renders:\n"
            "      - chapters/regression.qmd\n"
            "      - chapters/stat_tests.qmd\n"
            "    dir: epirhandbook/2.8/groups/analysis\n"
            '    tags: ["2.8"]\n'
            "    base: null\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("name", str(ctx.exception))

    def test_list_form_renders_rejects_non_qmd_element(self):
        # Stage 2: every element of the list MUST be a non-empty .qmd
        # string. A non-string entry, or an entry with the wrong suffix,
        # MUST NOT pass because the list is non-empty.
        text = (
            "images:\n"
            "  - name: epirhandbook-analysis\n"
            "    description: a test image\n"
            "    renders:\n"
            "      - chapters/regression.qmd\n"
            "      - chapters/stat_tests.Rmd\n"
            "    dir: epirhandbook/2.8/groups/analysis\n"
            '    tags: ["2.8"]\n'
            "    base: null\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("renders", str(ctx.exception))

    def test_group_image_without_renders_is_rejected(self):
        # Requirement 4: a record whose dir has a 'groups' path segment MUST
        # declare renders. The same rule applies to 'chapters'. The test uses
        # a string-form record, so it cannot fail for a different reason.
        text = (
            "images:\n"
            "  - name: epirhandbook-analysis\n"
            "    description: a test image\n"
            "    dir: epirhandbook/2.8/groups/analysis\n"
            '    tags: ["2.8"]\n'
            "    base: null\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("renders", str(ctx.exception))

    def test_duplicate_image_names_are_rejected(self):
        # Every later structure uses the name as key and would keep only the
        # last duplicate. A change under the first would plan the dir and tags
        # of the second.
        text = (
            "images:\n"
            '  - name: dup\n    description: a test image\n    dir: a\n    tags: ["1"]\n    base: null\n'
            '  - name: dup\n    description: a test image\n    dir: b\n    tags: ["2"]\n    base: null\n'
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("duplicate", str(ctx.exception).lower())


class TestMergedCatalogs(unittest.TestCase):
    """The catalog is in two hand-maintained files. The root images.yaml
    holds rbase, and epirhandbook/2.9/images.yaml holds the 2.9 line. Base
    edges cross the two files: epirhandbook-common is FROM rbase. The
    planner MUST see the two files merged. Otherwise `rbase` looks like a
    typo, and the whole plan fails. An earlier check of the schema alone
    missed this: validate_catalog passes on the split fixture alone, but
    the real planner (build_plan) raises."""

    def _write(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    ROOT = (
        "images:\n"
        "  - name: rbase\n    description: a test image\n    dir: rbase/4.3.2\n"
        '    tags: ["4.3.2"]\n    base: null\n'
    )
    SPLIT = (
        "images:\n"
        "  - name: epirhandbook-common\n    description: a test image\n    dir: epirhandbook/2.6/common\n"
        '    tags: ["2.6"]\n    base: "rbase:4.3.2"\n'
    )

    def test_cross_file_base_edge_resolves_when_merged(self):
        root, split = self._write(self.ROOT), self._write(self.SPLIT)
        images = plan.load_catalogs([root, split])
        self.assertEqual(len(images), 2)
        # The real boundary: build_plan MUST work, not only the schema
        # check. The cascade MUST also cross the file boundary: a change to
        # rbase MUST reach epirhandbook-common, in the other file.
        r = plan.build_plan(images, changed_images=["rbase"])
        self.assertEqual(names(r), {"rbase", "epirhandbook-common"})
        self.assertEqual(r["layers"][0][0]["name"], "rbase")

    def test_split_catalog_alone_is_rejected_by_the_planner(self):
        # The split fixture alone leaves the base with no definition. The
        # error comes from topological_order(), before build_plan() reads
        # changed_images, so the test needs no selection argument.
        split = self._write(self.SPLIT)
        with self.assertRaises(ValueError) as ctx:
            plan.build_plan(plan.load_catalogs([split]))
        self.assertIn("rbase", str(ctx.exception))

    def test_same_name_in_two_catalogs_is_rejected(self):
        a, b = self._write(self.ROOT), self._write(self.ROOT)
        with self.assertRaises(ValueError) as ctx:
            plan.load_catalogs([a, b])
        self.assertIn("already defined", str(ctx.exception))

    # --- Unit F: no .qmd rendered by more than one image, across the whole
    # combined set of --images-yaml inputs, not per file. The tests use
    # plain string-form records, so the list-form type check cannot make
    # them fail. They were still shown to fail first.

    CHAPTER_A = (
        "images:\n"
        "  - name: epirhandbook-basics\n"
        "    description: a test image\n"
        "    renders: chapters/basics.qmd\n"
        "    dir: epirhandbook/2.8/chapters/basics\n"
        '    tags: ["2.8"]\n    base: null\n'
    )
    # The dir basename MUST still be 'basics' here (a different parent
    # path, the same last segment), and the name MUST still end in
    # '-basics'. Each image MUST pass the stem/dir/name checks
    # (rule (i)/(ii)) alone. Then the only failure this fixture can cause
    # is the cross-image duplicate-.qmd rule under test. An earlier version
    # gave B a different dir basename ('basics-again'). The test then
    # passed for the wrong reason, because the stem-vs-dir-basename check
    # failed first. A read of the raised message found this.
    CHAPTER_B_SAME_QMD = (
        "images:\n"
        "  - name: epirhandbook-other-basics\n"
        "    description: a test image\n"
        "    renders: chapters/basics.qmd\n"
        "    dir: epirhandbook/2.8/other/chapters/basics\n"
        '    tags: ["2.8"]\n    base: null\n'
    )

    def test_qmd_rendered_by_two_images_across_catalogs_is_rejected(self):
        a = self._write(self.CHAPTER_A)
        b = self._write(self.CHAPTER_B_SAME_QMD)
        with self.assertRaises(ValueError) as ctx:
            plan.load_catalogs([a, b])
        msg = str(ctx.exception)
        self.assertIn("chapters/basics.qmd", msg)
        self.assertIn("epirhandbook-basics", msg)
        self.assertIn("epirhandbook-other-basics", msg)

    def test_qmd_rendered_by_two_images_in_the_same_file_is_rejected(self):
        # The combined-set rule also finds a duplicate within one file.
        # load_catalogs sees the whole merged set, from any number of files.
        text = (
            "images:\n"
            "  - name: epirhandbook-basics\n"
            "    description: a test image\n"
            "    renders: chapters/basics.qmd\n"
            "    dir: epirhandbook/2.8/chapters/basics\n"
            '    tags: ["2.8"]\n    base: null\n'
            "  - name: epirhandbook-other-basics\n"
            "    description: a test image\n"
            "    renders: chapters/basics.qmd\n"
            "    dir: epirhandbook/2.8/other/chapters/basics\n"
            '    tags: ["2.8"]\n    base: null\n'
        )
        a = self._write(text)
        with self.assertRaises(ValueError) as ctx:
            plan.load_catalogs([a])
        self.assertIn("chapters/basics.qmd", str(ctx.exception))


class TestAgainstRealCatalog(unittest.TestCase):
    """Canary: the real catalogs still have the shape that the tests above
    use. The only public deliverable is the 2.9 catalog. 2.5 to 2.8 are only
    in git history, and the CI planner never loaded them. The root
    images.yaml holds only the base image (rbase:4.6.0-2026-07-01).
    epirhandbook/2.9/images.yaml holds epirhandbook-common, the six group
    images and the monolith, FROM this rbase across the file boundary.

    A missing catalog file fails every test here. These tests read the two
    files that build.yml passes. So a catalog that moved or was deleted is a
    defect, not a reason to skip."""

    def _real_catalog_paths(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        root_yaml = os.path.join(repo_root, "images.yaml")
        split_yaml = os.path.join(repo_root, "epirhandbook", "2.9", "images.yaml")
        return root_yaml, split_yaml

    def test_real_images_yaml_matches_assumed_shape(self):
        root_yaml, _ = self._real_catalog_paths()
        images = plan.load_images(root_yaml)
        by_name = {img["name"]: img for img in images}
        self.assertEqual(set(by_name), {"rbase"})
        self.assertIsNone(by_name["rbase"]["base"])
        self.assertEqual(by_name["rbase"]["dir"], "rbase/4.6.0")
        self.assertEqual(by_name["rbase"]["tags"], ["4.6.0-2026-07-01"])
        self.assertTrue(by_name["rbase"]["live"])

    def test_real_catalogs_merge_and_plan_2_9_only(self):
        # Runs the planner as production does: build.yml passes these two
        # real files. The test checks that the cross-file base edge
        # (epirhandbook-common:2.9 FROM rbase:4.6.0-2026-07-01) resolves with
        # no error. It also checks that no 2.5/2.6/2.7/2.8/4.3.2 artifact is
        # in the merged plan. `changed_images` lists every real name, to
        # select all images for this shape check. No nightly or "select
        # everything" mode exists now.
        root_yaml, split_yaml = self._real_catalog_paths()
        images = plan.load_catalogs([root_yaml, split_yaml])
        r = plan.build_plan(images, changed_images=[img["name"] for img in images])
        image_names = names(r)
        self.assertIn("rbase", image_names)
        self.assertIn("epirhandbook-common", image_names)
        # rbase + common + the six groups + the monolith
        self.assertEqual(len(image_names), 9)
        self.assertNotIn("epirhandbook", image_names)  # the old 2.5 monolith name
        by_name = {img["name"]: img for layer in r["layers"] for img in layer}
        self.assertEqual(by_name["rbase"]["tags"], ["4.6.0-2026-07-01"])
        for name, img in by_name.items():
            self.assertNotIn("2.5", img["tags"])
            self.assertNotIn("2.6", img["tags"])
            self.assertNotIn("2.7", img["tags"])
            self.assertNotIn("2.8", img["tags"])
            self.assertNotIn("4.3.2", img["tags"])
        self.assertEqual(r["layers"][0][0]["name"], "rbase")  # base-most first

    def test_every_real_image_carries_a_description(self):
        # The nine published images each stamp their own
        # org.opencontainers.image.description label. A record that lost its
        # description would publish the label it inherits from its base.
        root_yaml, split_yaml = self._real_catalog_paths()
        images = plan.load_catalogs([root_yaml, split_yaml])
        self.assertEqual(len(images), 9)
        for img in images:
            self.assertIsInstance(img["description"], str)
            self.assertTrue(img["description"].strip(), img["name"])

    def test_common_change_cascades_to_every_group_but_not_rbase(self):
        # Discriminator (a): a change to common's dir MUST plan common, the
        # six group images and the monolith (the cascade), but not rbase.
        # The cascade only goes from base to dependent, never back.
        root_yaml, split_yaml = self._real_catalog_paths()
        images = plan.load_catalogs([root_yaml, split_yaml])
        r = plan.build_plan(images, changed_images=["epirhandbook-common"])
        image_names = names(r)
        # common + the six groups + the monolith
        self.assertEqual(len(image_names), 8)
        self.assertIn("epirhandbook-common", image_names)
        self.assertIn("epirhandbook-monolith", image_names)
        self.assertNotIn("rbase", image_names)

    def test_single_group_change_selects_only_that_group(self):
        # Discriminator (b): a change to one group image selects only that
        # image. There is no cascade, because no image in this catalog is
        # FROM a group. Nothing goes to common or rbase.
        root_yaml, split_yaml = self._real_catalog_paths()
        images = plan.load_catalogs([root_yaml, split_yaml])
        r = plan.build_plan(images, changed_images=["epirhandbook-basics"])
        self.assertEqual(names(r), {"epirhandbook-basics"})

    def test_unchanged_real_catalog_selects_nothing(self):
        # Discriminator (d), the plan.py half: an empty --changed-image list
        # plans nothing. changed_images.py gives that list when every image is
        # unchanged since its published revision.
        root_yaml, split_yaml = self._real_catalog_paths()
        images = plan.load_catalogs([root_yaml, split_yaml])
        r = plan.build_plan(images, changed_images=[])
        self.assertEqual(names(r), set())
        self.assertEqual(r["trigger"], "none")


class TestBuildContextAndChapterRenders(unittest.TestCase):
    """From the round 2 review. CI used `dir` as the docker build context.
    But a 2.6 chapter's Dockerfile COPYs from epirhandbook/2.6, not from the
    chapter directory. So CI planned the images and then failed at
    `docker build` ('/pak_install_subset.R': not found). `context` keeps the
    two facts apart:
    dir = this image's own files (change scope and Dockerfile location),
    context = the root that COPY paths resolve against."""

    def _validate(self, text):
        return plan.validate_catalog(yaml.safe_load(text), "<test>")

    ROW = (
        "images:\n"
        "  - name: epirhandbook-basics\n"
        "    description: a test image\n"
        "    renders: new_pages/basics.qmd\n"
        "    dir: epirhandbook/2.6/chapters/basics\n"
        "    context: epirhandbook/2.6\n"
        '    tags: ["2.6"]\n'
        "    base: null\n"
    )

    def test_context_is_accepted_and_reaches_the_plan(self):
        imgs = self._validate(self.ROW)
        self.assertEqual(imgs[0]["context"], "epirhandbook/2.6")
        r = plan.build_plan(imgs, changed_images=["epirhandbook-basics"])
        self.assertEqual(r["layers"][0][0]["context"], "epirhandbook/2.6")

    def test_context_defaults_to_dir_when_absent(self):
        # rbase, the one live image that omits `context`: its Dockerfile is
        # in its own context.
        text = (
            "images:\n  - name: rbase\n    description: a test image\n    dir: rbase/4.3.2\n"
            '    tags: ["4.3.2"]\n    base: null\n'
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

    def test_group_image_under_groups_segment_without_renders_is_rejected(self):
        # The other half of requirement 4, with the DIR_RE-shaped fixtures
        # of this class. 'groups' as a path segment, not as part of another
        # word, MUST cause the same error as 'chapters'.
        text = (
            "images:\n"
            "  - name: epirhandbook-analysis\n"
            "    description: a test image\n"
            "    dir: epirhandbook/2.8/groups/analysis\n"
            '    tags: ["2.8"]\n'
            "    base: null\n"
        )
        with self.assertRaises(ValueError) as ctx:
            self._validate(text)
        self.assertIn("renders", str(ctx.exception))

    def test_groups_as_a_word_fragment_not_a_segment_does_not_require_renders(self):
        # A segment match, not a substring match. A dir like
        # 'epirhandbook/subgroups' contains the substring 'groups' but has no
        # 'groups' path segment. So it MUST NOT need to declare renders. This
        # shows that rule 4 splits on '/', and does not use 'in' on the raw
        # string.
        text = (
            "images:\n"
            "  - name: epirhandbook-subgroups\n"
            "    description: a test image\n"
            "    dir: epirhandbook/subgroups\n"
            '    tags: ["2.8"]\n'
            "    base: null\n"
        )
        images = self._validate(text)
        self.assertEqual(images[0]["dir"], "epirhandbook/subgroups")


class TestChapterImageRows(unittest.TestCase):
    """plan.chapter_image_rows(), the pure function behind --chapter-images.
    It gives one row per rendered .qmd, for both the string and list forms
    of `renders`. The chapter id is the stem of each .qmd. It keeps catalog
    order, and list order within a list-form record. It never sorts."""

    def test_string_form_yields_one_row(self):
        images = [
            {"name": "epirhandbook-basics", "renders": "chapters/basics.qmd",
             "dir": "epirhandbook/2.7/chapters/basics", "tags": ["2.7"], "base": None},
        ]
        self.assertEqual(
            plan.chapter_image_rows(images),
            [("basics", "epirhandbook-basics:2.7", "chapters/basics.qmd")],
        )

    def test_list_form_yields_one_row_per_qmd_in_list_order(self):
        images = [
            {"name": "epirhandbook-analysis",
             "renders": ["chapters/regression.qmd", "chapters/stat_tests.qmd"],
             "dir": "epirhandbook/2.8/groups/analysis", "tags": ["2.8"], "base": None},
        ]
        self.assertEqual(
            plan.chapter_image_rows(images),
            [
                ("regression", "epirhandbook-analysis:2.8", "chapters/regression.qmd"),
                ("stat_tests", "epirhandbook-analysis:2.8", "chapters/stat_tests.qmd"),
            ],
        )

    def test_chapter_id_comes_from_the_qmd_stem_not_the_group_dir_basename(self):
        # A simple implementation based on the dir basename gets this case
        # wrong. The dir basename is the group name ('analysis'), not the
        # name of one chapter. The chapter id MUST come from the .qmd.
        images = [
            {"name": "epirhandbook-analysis", "renders": ["chapters/regression.qmd"],
             "dir": "epirhandbook/2.8/groups/analysis", "tags": ["2.8"], "base": None},
        ]
        rows = plan.chapter_image_rows(images)
        self.assertEqual(rows[0][0], "regression")
        self.assertNotEqual(rows[0][0], "analysis")

    def test_catalog_order_is_preserved_not_sorted(self):
        images = [
            {"name": "epirhandbook-zeta", "renders": "chapters/zeta.qmd",
             "dir": "epirhandbook/2.7/chapters/zeta", "tags": ["2.7"], "base": None},
            {"name": "epirhandbook-alpha", "renders": "chapters/alpha.qmd",
             "dir": "epirhandbook/2.7/chapters/alpha", "tags": ["2.7"], "base": None},
        ]
        chapters = [row[0] for row in plan.chapter_image_rows(images)]
        self.assertEqual(chapters, ["zeta", "alpha"])

    def test_image_without_renders_yields_no_rows(self):
        # rbase / epirhandbook-common: renders no single .qmd.
        images = [
            {"name": "epirhandbook-common", "dir": "epirhandbook/2.7/common",
             "tags": ["2.7"], "base": None},
        ]
        self.assertEqual(plan.chapter_image_rows(images), [])

    def test_mixed_string_and_list_form_catalog(self):
        images = [
            {"name": "epirhandbook-basics", "renders": "chapters/basics.qmd",
             "dir": "epirhandbook/2.7/chapters/basics", "tags": ["2.7"], "base": None},
            {"name": "epirhandbook-analysis",
             "renders": ["chapters/regression.qmd", "chapters/stat_tests.qmd"],
             "dir": "epirhandbook/2.8/groups/analysis", "tags": ["2.8"], "base": None},
        ]
        self.assertEqual(
            plan.chapter_image_rows(images),
            [
                ("basics", "epirhandbook-basics:2.7", "chapters/basics.qmd"),
                ("regression", "epirhandbook-analysis:2.8", "chapters/regression.qmd"),
                ("stat_tests", "epirhandbook-analysis:2.8", "chapters/stat_tests.qmd"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
