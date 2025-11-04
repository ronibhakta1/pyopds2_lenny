# pyopds_lenny/__init__.py
from typing import List, Tuple, Optional
from pyopds2_openlibrary import OpenLibraryDataProvider, OpenLibraryDataRecord, Link 


class LennyDataRecord(OpenLibraryDataRecord):
    """A record that extends OpenLibrary metadata with local Lenny borrow links."""

    lenny_id: Optional[int] = None
    
    @property
    def type(self) -> str:
        return "http://schema.org/Book"
    
    def links(self) -> List[Link]:
        """Override acquisition links to point to Lenny's endpoints."""
        links = super().links()
        if self.lenny_id:
            # Replace Open Library borrow/download links with Lenny local links
            base_uri = f"/v1/api/items/{self.lenny_id}"
            links = [
            Link(
                href=f"{base_uri}/borrow",
                rel="http://opds-spec.org/acquisition/borrow",
                type="application/json",
            ),
            Link(
                href=f"{base_uri}/return",
                rel="http://opds-spec.org/acquisition/borrow",
                type="application/json",
            ),
        ]
        return links
    
    def images(self) -> List[Link]:
        if hasattr(self, "cover_i") and self.cover_i:
            return [Link(
            href=f"https://covers.openlibrary.org/b/id/{self.cover_i}-L.jpg",
            rel="http://opds-spec.org/image",
            type="image/jpeg",
            )]
        return None


def _unwrap_search_response(resp):
    """Normalize different shapes returned by OpenLibraryDataProvider.search.

    Returns a tuple (records_iterable, total_or_None).
    Accepts tuple-like (records, total), objects with attributes
    ('records','docs','items','data'), or any iterable.
    """
    # Tuple-like (records, total)
    if isinstance(resp, tuple):
        records = resp[0] if len(resp) >= 1 else []
        total = resp[1] if len(resp) > 1 else None
        return records, total

    # Object with common attributes
    for attr in ("records", "docs", "items", "data"):
        if hasattr(resp, attr):
            records = getattr(resp, attr)
            # Try to find a total-like attribute
            total = None
            for tot_attr in ("total", "num_found", "numFound", "count", "size"):
                if hasattr(resp, tot_attr):
                    total = getattr(resp, tot_attr)
                    break
            return records, total

    # Fallback: try to coerce to list
    try:
        records = list(resp)
        return records, None
    except Exception:
        raise TypeError("cannot unpack non-iterable search response from OpenLibraryDataProvider.search")


class LennyDataProvider(OpenLibraryDataProvider):
    """A DataProvider that adapts Open Library metadata for Lenny's local catalog."""

    @staticmethod
    def search(
        query: str,
        numfound: int,
        limit: int,
        offset: int,
        lenny_ids: Optional[List[int]] = None,
    ) -> Tuple[List[LennyDataRecord], int]:
        """
        Perform a metadata search using Open Library's data provider,
        given a pre-computed query from Lenny.
        """
        # Use OpenLibraryDataProvider to fetch enriched metadata. Normalize
        # whatever shape the provider returns into (records_iterable, total).
        resp = OpenLibraryDataProvider.search(
            query=query,
            limit=limit,
            offset=offset,
        )

        ol_records, total = _unwrap_search_response(resp)

        # Adapt OpenLibraryDataRecords to LennyDataRecords
        lenny_records = []
        for idx, record in enumerate(ol_records):
            data = record.model_dump()
            data["lenny_id"] = lenny_ids[idx] if lenny_ids and idx < len(lenny_ids) else None
            lenny_records.append(LennyDataRecord.model_validate(data))

    # Prefer the total from the upstream provider when available.
    return lenny_records, (total if total is not None else numfound)