"""HTTP surface for the video catalog.

Read-only, and unauthenticated for the same reason the knowledge base is: this
is published educational material about a public programme. There is nothing
here a reader could not be shown.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.videos.catalog import all_videos
from app.videos.schemas import VideoListOut, to_out

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("", response_model=VideoListOut)
def list_videos() -> VideoListOut:
    """Every video in the library.

    Deliberately NOT filtered by persona. `for_persona` governs what may be
    OFFERED unasked mid-conversation; the panel is a reader opening a library on
    purpose, and a guardian or a teacher who wants to watch a children's story
    -- to decide whether to show it to a class, most obviously -- should not
    find it hidden.
    """
    return VideoListOut(videos=[to_out(video) for video in all_videos()])
