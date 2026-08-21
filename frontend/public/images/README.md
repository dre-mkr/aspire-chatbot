# Landing background artwork

`hero-bg.webp` (68 KB) with `hero-bg.jpg` (98 KB) as the fallback, referenced
through `image-set()` by the landing hero and by the About, Parents and
Educators views.

## One image, four surfaces

The design bundle shipped this artwork twice, as `hero-bg.png` and
`aspire-world-bg.png`. The two files were byte-identical, so the second name
bought nothing and both now resolve to the same file.

## Why it is not the PNG that arrived

The two PNGs in the bundle were **corrupt**. A valid PNG opens `89 50 4E 47`;
both opened `EF BF BD 50 4E 47` — the `0x89` replaced by U+FFFD, with 777,328
more replacement sequences through a 3.4 MB file. The binary had been round
tripped through UTF-8 text somewhere in the export, `file` reported them as
`data`, and no browser would have drawn either one.

The artwork here was re-exported from the original and encoded properly:

    source PNG   1830 KB   1672x941
    webp           68 KB   1600 wide, q72
    jpeg           98 KB   1600 wide, q74, mozjpeg

That is a 96% reduction, and it matters: the readers are children in St Kitts
and Nevis on phones, on mobile data. The image also sits under a near-opaque
white veil in every usage, so it never needs to be crisp — quality 72 is
indistinguishable once the veil is over it.

## If you replace it

Keep both formats and both names, re-run the same encode, and check the result
really is an image before committing it:

    file hero-bg.webp    # must say "RIFF ... Web/P image", never "data"
