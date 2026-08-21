# Landing background images — NOT COMMITTED, and here is why

`hero-bg.png` and `aspire-world-bg.png` are referenced by the landing and the
About / Parents / Educators views, and they are deliberately absent.

The two files that arrived with the design bundle were **corrupt**. A valid PNG
opens with `89 50 4E 47`; both opened with `EF BF BD 50 4E 47` — the `0x89` had
been replaced by U+FFFD, the Unicode replacement character, and the 3.4 MB file
carried 777,328 more of them. The binary had been round-tripped through UTF-8
text somewhere in the export. `file` reported them as `data`, not as images, and
no browser would have drawn either one.

They were also byte-identical to each other, so the bundle shipped one broken
image under two names.

## What happens without them

Nothing breaks. Each usage layers the image *under* a white gradient, so the
background falls back to the gradient alone. The page is quieter than intended
but correct.

## To restore

Drop the real artwork in here under these two names. Please also:

- export at the size actually needed — the originals were 3.4 MB each, and the
  readers are on phones on mobile data in St Kitts and Nevis
- prefer WebP with a PNG or JPEG fallback
- check the file really is what it claims: `file hero-bg.png` should say
  `PNG image data`, never `data`
