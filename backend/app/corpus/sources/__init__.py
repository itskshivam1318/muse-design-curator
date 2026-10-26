"""Source adapters. Each yields ManifestItems from an official API or bulk file."""

from app.corpus.sources.aic import AicSource
from app.corpus.sources.base import BaseSource, ManifestItem, Source
from app.corpus.sources.commons import CommonsSource
from app.corpus.sources.met import MetSource
from app.corpus.sources.openverse import OpenverseSource
from app.corpus.sources.pexels import PexelsSource
from app.corpus.sources.rijks import RijksSource
from app.corpus.sources.self_capture import SelfCaptureSource
from app.corpus.sources.smithsonian import SmithsonianSource

SOURCES: dict[str, type[BaseSource]] = {
    cls.name: cls
    for cls in (
        CommonsSource, OpenverseSource, MetSource, SmithsonianSource, AicSource, RijksSource,
        PexelsSource, SelfCaptureSource,
    )
}  # fmt: skip

__all__ = ["SOURCES", "BaseSource", "ManifestItem", "Source"]
