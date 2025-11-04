"""
pyopds2_lenny — adapt OpenLibrary provider records to Lenny endpoints and OPDS 2.0 image format.
- Do NOT hard-code a public URL in this package. Caller (lenny/core/api) passes base_url and an optional
    mapping from OpenLibrary record -> lenny_id so exact Lenny endpoints can be emitted.
- Produces acquisition links that match Lenny endpoints:
    /v1/api/items/{lenny_id}/borrow
    /v1/api/items/{lenny_id}/return
    /v1/api/items/{lenny_id}/readium/manifest.json
- images() returns a list of dicts following OPDS 2.0 examples (href, type, optional height/width).
"""
from typing import List, Optional, Dict, Any
from urllib.parse import quote

from opds2 import DataProvider, SearchResponse, Link, Metadata
from pyopds2_openlibrary import OpenLibraryDataProvider, OpenLibraryDataRecord, map_ol_format_to_mime

def _extract_olid_from_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    return key.split("/")[-1]

def _olid_to_int(olid: Optional[str]) -> Optional[int]:
    if not olid:
        return None
    digits = "".join(ch for ch in olid if ch.isdigit())
    return int(digits) if digits else None

class LennyDataRecord(OpenLibraryDataRecord):
    """
    Extend OpenLibraryDataRecord with Lenny-specific link generation and OPDS-style images payload.
    The caller (LennyDataProvider.search) attaches:
        - _lenny_base_url: Optional[str]  (public base url, e.g. https://lenny.example)
        - _lenny_id: Optional[int]       (local Lenny item id to produce exact endpoints)
    """

    lenny_id: Optional[int] = None  # preserved as model field for convenience (optional)
    # runtime-only attributes are attached by LennyDataProvider.search: _lenny_base_url, _lenny_id

    def _get_base(self) -> Optional[str]:
        return getattr(self, "_lenny_base_url", None)

    def _get_lenny_id(self) -> Optional[int]:
        # prefer explicit attribute set on model, fall back to runtime private attr
        return getattr(self, "_lenny_id", getattr(self, "lenny_id", None))

    def _quote(self, s: str) -> str:
        return quote(s, safe="")

    def lenny_acquisition_href(self, provider, edition_or_work_key: str) -> Optional[str]:
        base = self._get_base()
        lenny_id = self._get_lenny_id()

        # If caller provided base_url and a lenny_id, produce canonical Lenny endpoints.
        if base and lenny_id:
            access = (provider.access or "borrow").lower()
            # access 'open' or 'read' -> manifest/readium endpoint
            if access in ("open", "read"):
                return f"{base.rstrip('/')}/v1/api/items/{lenny_id}/readium/manifest.json"
            # borrow/return/etc. map to explicit verbs on the item resource
            return f"{base.rstrip('/')}/v1/api/items/{lenny_id}/{access}"

        # No lenny id/base_url available: fall back to provider url if present
        if getattr(provider, "url", None):
            return provider.url

        # Final fallback: construct an OpenLibrary URL from the key
        if edition_or_work_key:
            if edition_or_work_key.startswith("/"):
                return f"https://openlibrary.org{edition_or_work_key}"
            return f"https://openlibrary.org/{edition_or_work_key}"

        return None

    def links(self) -> List[Link]:
        """
        Return a list of Link objects:
        - always include self/alternate pointing to OpenLibrary
        - if we can resolve Lenny endpoints (base_url + lenny_id) include acquisition links matching Lenny routes
        - otherwise include original acquisition links from OpenLibrary providers (if any)
        """
        edition = self.editions.docs[0] if self.editions and self.editions.docs else None
        book = edition or self
        base_links: List[Link] = [
            Link(rel="self", href=f"{OpenLibraryDataProvider.URL}{book.key}", type="text/html"),
            Link(rel="alternate", href=f"{OpenLibraryDataProvider.URL}{book.key}.json", type="application/json"),
        ]

        # If there are no providers, just return self/alternate
        if not edition or not edition.providers:
            return base_links

        # Build acquisition links: prefer Lenny endpoints when possible
        lenny_links: List[Link] = []
        for provider in edition.providers:
            mime = map_ol_format_to_mime(provider.format) if provider.format else None
            href = self.lenny_acquisition_href(provider, book.key)
            if not href:
                continue
            rel = f"http://opds-spec.org/acquisition/{provider.access}" if provider.access else "http://opds-spec.org/acquisition"
            lenny_links.append(Link(href=href, rel=rel, type=mime))
        return base_links + lenny_links

    def images(self) -> Optional[List[Dict[str, Any]]]:
        """
        Return images in the OPDS-style structure the user requested:
        [
            {"href": "...", "type": "image/jpeg", "height": 1400, "width": 800},
            {"href": "...", "type": "image/jpeg", "height": 700, "width": 400},
            {"href": "...", "type": "image/svg+xml"}
        ]
        Notes:
        - We cannot reliably infer exact height/width from OpenLibrary cover ids; include height/width only if present
        on the record (e.g. some providers or your DB may enrich this).
        - We always provide multiple sizes (L, M, S) using covers.openlibrary.org when cover_i is available.
        """
        edition = self.editions.docs[0] if self.editions and self.editions.docs else None
        book = edition or self

        if not getattr(book, "cover_i", None):
            return None

        cover_id = book.cover_i
        images: List[Dict[str, Any]] = []

        # Large
        images.append({"href": f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg", "type": "image/jpeg"})
        # Medium
        images.append({"href": f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg", "type": "image/jpeg"})
        # Small
        images.append({"href": f"https://covers.openlibrary.org/b/id/{cover_id}-S.jpg", "type": "image/jpeg"})

        # If record has explicit dimensions, add them to the matching entries.
        # Common optional fields to check (these are not provided by OL by default):
        cover_height = getattr(book, "cover_height", None) or getattr(book, "height", None)
        cover_width = getattr(book, "cover_width", None) or getattr(book, "width", None)
        if cover_height and cover_width:
            # Attach to the large entry as best-effort example
            images[0]["height"] = cover_height
            images[0]["width"] = cover_width

        return images


class LennyDataProvider(DataProvider):
    """
    Queries OpenLibrary and returns SearchResponse whose records are LennyDataRecord
    instances. Caller must pass:
      - base_url: optional public base URL to build absolute Lenny endpoints
      - lenny_id_map: optional mapping that maps OpenLibrary identifiers -> Lenny item id
          Accepted keys in lenny_id_map: integer OL edition id (123), OLID string ("OL123M"),
          or OpenLibrary key ("/books/OL123M")
    """
    @staticmethod
    def search(
        query: str,
        limit: int = 50,
        offset: int = 0,
        sort: Optional[str] = None,
        base_url: Optional[str] = None,
        lenny_id_map: Optional[Dict[Any, int]] = None,
    ) -> SearchResponse:
        resp = OpenLibraryDataProvider.search(query, limit=limit, offset=offset, sort=sort)
        wrapped_records: List[Any] = []

        for r in resp.records:
            try:
                data = r.model_dump() if hasattr(r, "model_dump") else (r if isinstance(r, dict) else dict(r))
                lr = LennyDataRecord.model_validate(data)
            except Exception:
                # If validation fails, keep original record (best-effort)
                wrapped_records.append(r)
                continue

            # Attach runtime-only base url
            if base_url:
                setattr(lr, "_lenny_base_url", base_url)

            # Attempt to resolve a lenny_id from provided mapping
            if lenny_id_map:
                edition = lr.editions.docs[0] if lr.editions and lr.editions.docs else None
                book = edition or lr
                key = getattr(book, "key", None)  # e.g. "/books/OL123M"
                olid = _extract_olid_from_key(key)
                found = None
                if key and key in lenny_id_map:
                    found = lenny_id_map[key]
                elif olid and olid in lenny_id_map:
                    found = lenny_id_map[olid]
                else:
                    olid_int = _olid_to_int(olid) if olid else None
                    if olid_int and olid_int in lenny_id_map:
                        found = lenny_id_map[olid_int]
                if found:
                    # attach as both model field and runtime private attr for safety
                    try:
                        lr.lenny_id = found
                    except Exception:
                        pass
                    setattr(lr, "_lenny_id", found)

            wrapped_records.append(lr)

        return SearchResponse(wrapped_records, resp.total, resp.request)