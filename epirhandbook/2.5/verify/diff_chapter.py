import sys, re, html, difflib
def text(f):
    try: s = open(f, encoding='utf-8', errors='replace').read()
    except Exception: return None
    s = re.sub(r'<script.*?</script>', ' ', s, flags=re.S)
    s = re.sub(r'<style.*?</style>', ' ', s, flags=re.S)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    s = re.sub(r'\d{4}-\d{2}-\d{2}', 'DATE', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()
a = text(sys.argv[1]); b = text(sys.argv[2])
if a is None or b is None:
    print(f"{sys.argv[3]:22} MISSING rendered={a is not None} ref={b is not None}"); sys.exit()
wa, wb = a.split(' '), b.split(' ')
r = difflib.SequenceMatcher(None, wa, wb).ratio()
print(f"{sys.argv[3]:22} similarity={r:.4f}  words rendered={len(wa):6} ref={len(wb):6}")
