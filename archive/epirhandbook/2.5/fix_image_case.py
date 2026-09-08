#!/usr/bin/env python3
# Content-preserving case-insensitivity shim for rendering the handbook on a
# case-sensitive (Linux) filesystem.
#
# The handbook was authored and rendered on macOS (case-insensitive), so image
# references whose case does not match the real file resolve there but 404 on
# Linux. Example: index.qmd references images/"Epi R Handbook banner beige ..."
# (lowercase) while the committed file is "...Banner Beige..." (capital); the
# live site even embeds the capital name, proving the production render was on a
# case-insensitive FS. For each referenced images/<name> that does not exist
# exactly but matches a real file case-insensitively, create a symlink with the
# exact referenced name. No .qmd is edited — content is untouched.
#
# Usage: python3 fix_image_case.py [handbook_source_dir]   (default: cwd)
import os, re, glob, sys

root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
imgdir = os.path.join(root, "images")

actual = {}                                   # real files, keyed lowercase
for f in os.listdir(imgdir):
    actual.setdefault(f.lower(), f)

refs = set()
qmds = ([os.path.join(root, "index.qmd")]
        + sorted(glob.glob(os.path.join(root, "index.*.qmd")))
        + sorted(glob.glob(os.path.join(root, "new_pages", "*.qmd"))))
pat_here = re.compile(r'here::here\(\s*"images"\s*,\s*"([^"]+)"')
pat_path = re.compile(r'images/([^"\')\s]+\.(?:png|jpe?g|gif|svg))', re.I)
for q in qmds:
    try:
        txt = open(q, encoding="utf-8", errors="ignore").read()
    except FileNotFoundError:
        continue
    for m in pat_here.finditer(txt):
        refs.add(m.group(1))
    for m in pat_path.finditer(txt):
        refs.add(m.group(1))

created, ok, missing = 0, 0, []
for r in sorted(refs):
    if "/" in r:                              # nested path, skip
        continue
    target = os.path.join(imgdir, r)
    if os.path.exists(target):
        ok += 1
        continue
    match = actual.get(r.lower())
    if match:
        os.symlink(match, target)             # relative symlink inside images/
        created += 1
        print(f"  SYMLINK  {r!r} -> {match!r}")
    else:
        missing.append(r)                     # e.g. commented-out refs; harmless

print(f"\nrefs={len(refs)} exact_ok={ok} symlinks_created={created} "
      f"unresolved={len(missing)}")
for m in missing:
    print("  unresolved (check if commented-out / cover-image only):", m)
