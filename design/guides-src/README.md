# Guide artwork — masters

The illustrated guides at their original 1254×1254, 8.8 MB for the five.

**Not in `frontend/public/`, on purpose.** Everything under `public/` is the web
root: it is copied verbatim into the build and served. These are masters that
nothing references, so putting them there publishes nine megabytes of art no
page ever asks for.

What the app actually loads is in `frontend/public/guides/` — 480px WebP at
~30 KB each, with a 320px palette PNG so `<picture>` has a floor. Regenerate
from here after replacing a master:

    backend/.venv/bin/python - <<'PY'
    from PIL import Image
    from pathlib import Path
    for src, slug in [("SKYE","skye"),("Kaleb","kaleb"),("Zion","zion"),
                      ("Imani","imani"),("Azuri","azuri")]:
        im = Image.open(Path("design/guides-src") / f"{src}.png").convert("RGB")
        out = Path("frontend/public/guides")
        im.resize((480,480), Image.LANCZOS).save(out / f"{slug}.webp", "WEBP",
                                                 quality=82, method=6)
        im.resize((320,320), Image.LANCZOS).quantize(colors=256).save(
            out / f"{slug}.png", "PNG", optimize=True)
    PY

Keep them square. The avatars are circles and `object-fit: cover` will crop
anything that is not.
