# transmission_chains: seeded A/B (split vs monolith)

`transmission_chains` is the one chapter whose similarity differs from Phase 3's
monolith run (0.9897 -> 0.9890). It runs an **unseeded** stochastic contact-network
simulation, so *any* two renders differ — which means a same-day A/B cannot settle
whether the SPLIT caused the delta. Pinning the RNG can.

## Method
`set.seed(20260723)` was injected as a hidden setup chunk into **throwaway copies**
of the source (never the sealed `render_sep18`), and the chapter was rendered on
both images on the same day:

- split:    `epirhandbook-transmission_chains:2.6`
- monolith: `epirhandbook:2.5-p2ubuntu`

## Result — identical content
```
diff_chapter_parsed.py  ->  similarity=1.0000  hunks=0  words 4704 = 4704
```

Byte level: exactly **2 differing lines**, and the difference is JSON key ORDER in
a GLightbox options object:

```
< GLightbox({"openEffect":"zoom","closeEffect":"zoom",...})
> GLightbox({"closeEffect":"zoom",...,"openEffect":"zoom",...})
```

Semantically identical JSON — the same non-deterministic serialization Phase 3
documented for this script. No content, figure, or computed value differs.

## Conclusion
With the RNG pinned, the split image and the monolith image produce identical
renders. The 0.9897/0.9890 delta is entirely the chapter's own unseeded RNG, not
the package split.

Cleanup verified: throwaway copies deleted; `render_sep18/new_pages/transmission_chains.qmd`
contains 0 occurrences of `set.seed`; `ref_p2_book` remains read-only (49 pages).
