#!/usr/bin/env python3
# Freeze the reproduction evidence: for every language x chapter, the
# text-similarity of the Sep-18 render vs the live-site crawl, plus a content
# hash of both files compared (so the exact bytes are provenance-pinned even
# though the bulky HTML itself is not committed). Writes verify_manifest.tsv.
#
# Reproduce: render the Sep-18 content (epiRhandbook_eng @ c3cbc76, gis excluded,
# fix_image_case.py applied) on epirhandbook:2.5-p1 via quarto_runfile.R, crawl
# epirhandbook.com/<lang>/new_pages/*.html, then run this next to diff_chapter.py.
import re, os, glob, subprocess, statistics, hashlib

os.chdir(os.path.expanduser("~/ae"))

def sha16(f):
    try:
        return hashlib.sha256(open(f, "rb").read()).hexdigest()[:16]
    except OSError:
        return "NA"

def measure(rendered, ref):
    if not (os.path.exists(rendered) and os.path.exists(ref)):
        return None
    out = subprocess.run(["python3", "diff_chapter.py", rendered, ref, "x"],
                         capture_output=True, text=True).stdout
    m = re.search(r"similarity=([0-9.]+)\s+words rendered=\s*(\d+)\s+ref=\s*(\d+)", out)
    if not m:
        return None
    return float(m.group(1)), int(m.group(2)), int(m.group(3))

langs = ["en", "fr", "es", "vn", "jp", "pt", "tr", "ru"]
rows = []
for lang in langs:
    if lang == "en":
        rdir, ldir = "render_sep18/html_outputs/new_pages", "live_crawl"
    else:
        rdir, ldir = f"render_sep18/html_outputs/{lang}/new_pages", f"live_crawl_ml/{lang}"
    for lf in sorted(glob.glob(f"{ldir}/*.html")):
        if os.path.getsize(lf) < 2000:            # skip 404/placeholder live pages
            continue
        base = os.path.basename(lf)
        chapter = base.split(".")[0]
        rf = os.path.join(rdir, base)
        res = measure(rf, lf)
        if res is None:
            rows.append((lang, chapter, "NA", "NA", "NA", sha16(rf), sha16(lf)))
        else:
            s, rw, fw = res
            rows.append((lang, chapter, f"{s:.4f}", rw, fw, sha16(rf), sha16(lf)))

with open("verify_manifest.tsv", "w") as f:
    f.write("lang\tchapter\tsimilarity\trendered_words\tref_words\trendered_sha16\tref_sha16\n")
    for row in rows:
        f.write("\t".join(str(x) for x in row) + "\n")

print("lang  n   median   >=0.98  <0.90")
for lang in langs:
    sims = sorted(float(r[2]) for r in rows if r[0] == lang and r[2] != "NA")
    if not sims:
        continue
    print(f"{lang:4} {len(sims):>2}  {statistics.median(sims):.4f}   "
          f"{sum(1 for s in sims if s >= 0.98):>2}/{len(sims):<2}   {sum(1 for s in sims if s < 0.90)}")
print(f"\n{len(rows)} rows -> verify_manifest.tsv")
