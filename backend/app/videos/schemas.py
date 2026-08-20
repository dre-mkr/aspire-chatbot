"""What the videos endpoint returns."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.videos.catalog import PUBLIC_DIR, Video


class VideoOut(BaseModel):
    """One video, as the client needs it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str
    topic: str
    setting: str
    duration_seconds: int = Field(ge=0)

    #: A path under the site's own origin, never an absolute URL.
    #:
    #: The client is the only thing that turns this into a request, and keeping
    #: it relative means the same payload is correct on localhost, on the
    #: staging host and behind the CDN -- and that nothing here can ever point a
    #: reader off-site.
    src: str


class VideoListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    videos: list[VideoOut]


def to_out(video: Video) -> VideoOut:
    return VideoOut(
        id=video.id,
        title=video.title,
        description=video.description,
        topic=video.topic,
        setting=video.setting,
        duration_seconds=video.duration_seconds,
        src=f"{PUBLIC_DIR}/{video.filename}",
    )
