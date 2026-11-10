# -*- coding: utf-8 -*-
from .base import SiteAdapter, ParseError, make_not_found_evidence
from .anime_store import AnimeStoreAdapter
from .amiami import AmiAmiAdapter
from .amnibus import AmnibusAdapter
from .jumpcs import JumpCharacterStoreAdapter
from .hobbysearch import HobbySearchAdapter
from .animate import AnimateAdapter
from .local_library import LocalLibrary

__all__ = [
    "SiteAdapter", "ParseError", "make_not_found_evidence",
    "AnimeStoreAdapter", "AmiAmiAdapter", "JumpCharacterStoreAdapter",
    "HobbySearchAdapter", "AnimateAdapter", "AmnibusAdapter", "LocalLibrary",
]
