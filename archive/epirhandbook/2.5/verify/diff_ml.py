#!/usr/bin/env python3
# Diff each rendered language against the live-site crawl.
# EN:    render_sep18/html_outputs/new_pages/<ch>.html      vs live_crawl/<ch>.html
# <lang>:render_sep18/html_outputs/<lang>/new_pages/<ch>.<lang>.html vs live_crawl_ml/<lang>/<ch>.<lang>.html
import re, os, glob, subprocess
os.chdir(os.path.expanduser("~/ae"))

def sim(rendered, live):
    if not (os.path.exists(rendered) and os.path.exists(live)):
        return None
    out = subprocess.run(["python3", "diff_chapter.py", rendered, live, "x"],
                         capture_output=True, text=True).stdout
    m = re.search(r"similarity=([0-9.]+)", out)
    return float(m.group(1)) if m else None

langs = ["en", "fr", "es", "vn", "jp", "pt", "tr", "ru"]
print(f"{'lang':4} {'n':>3} {'median':>7} {'>=0.98':>7} {'<0.90':>6} {'missing':>7}   lowest-3")
print("-" * 78)
for lang in langs:
    if lang == "en":
        rdir, ldir = "render_sep18/html_outputs/new_pages", "live_crawl"
    else:
        rdir, ldir = f"render_sep18/html_outputs/{lang}/new_pages", f"live_crawl_ml/{lang}"
    sims, miss = [], 0
    for lf in sorted(glob.glob(f"{ldir}/*.html")):
        if os.path.getsize(lf) < 2000:      # skip 404/placeholder live pages
            continue
        base = os.path.basename(lf)
        s = sim(os.path.join(rdir, base), lf)
        if s is None:
            miss += 1
        else:
            sims.append((s, base))
    if not sims:
        print(f"{lang:4}   -       -       -      -   {miss:>7}   (no rendered pages)")
        continue
    sims.sort()
    vals = [s for s, _ in sims]
    med = vals[len(vals) // 2]
    ge98 = sum(1 for v in vals if v >= 0.98)
    lt90 = sum(1 for v in vals if v < 0.90)
    low = ", ".join(f"{s:.3f}:{c.split('.')[0]}" for s, c in sims[:3])
    print(f"{lang:4} {len(sims):>3} {med:>7.4f} {ge98:>3}/{len(sims):<3} {lt90:>6} {miss:>7}   {low}")
