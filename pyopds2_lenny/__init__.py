from typing import List, Tuple, Optional
from collections.abc import Mapping, Iterable
from pyopds2_openlibrary import OpenLibraryDataProvider, OpenLibraryDataRecord, Link
from pyopds2.provider import DataProvider


class LennyDataRecord(OpenLibraryDataRecord):
    """Extends OpenLibraryDataRecord with local borrow/return links for Lenny."""

    lenny_id: Optional[int] = None
    is_encrypted: bool = False

    @property
    def type(self) -> str:
        return "http://schema.org/Book"

    def links(self) -> List[Link]:
        """Override acquisition links to use Lenny's API endpoints.

        If the record was created with an `is_encrypted` flag the primary
        acquisition link will be `/borrow` (for encrypted/loaned content),
        otherwise `/read` for open-access/readable content. When encrypted
        we also include a `return` endpoint.
        """
        if not self.lenny_id:
            return super().links() or []

        lenny_links = [
            Link(
                rel="self",
                href=f"{LennyDataProvider.BASE_URL}opds/{self.lenny_id}",
                type="application/opds-publication+json",
                title=None,
                templated=False,
                properties=None,
            )
        ]
        
        base_uri = f"{LennyDataProvider.BASE_URL}items/{self.lenny_id}"
        if self.is_encrypted:
            lenny_links += [
                Link(
                    href=f"{base_uri}/borrow",
                    rel="http://opds-spec.org/acquisition/borrow",
                    type="application/json",
                    title=None,
                    templated=False,
                    properties=None,
                ),
                Link(
                    href=f"{base_uri}/return",
                    rel="http://librarysimplified.org/terms/return",
                    type="application/json",
                    title=None,
                    templated=False,
                    properties=None,
                ),
            ]
        else:
            lenny_links += [
                Link(
                    href=f"{base_uri}/read",
                    rel="http://opds-spec.org/acquisition/open-access",
                    type="application/json",
                    title=None,
                    templated=False,
                    properties=None,
                )
            ]
        return lenny_links

    def images(self) -> Optional[List[Link]]:
        """Provide cover image link based on Open Library cover ID."""
        if hasattr(self, "cover_i") and self.cover_i:
            return [
                Link(
                    href=f"https://covers.openlibrary.org/b/id/{self.cover_i}-L.jpg",
                    rel="http://opds-spec.org/image",
                    type="image/jpeg",
                    title=None,
                    templated=False,
                    properties=None,
                )
            ]
        return []


def _unwrap_search_response(resp):
    """Minimal normalizer for the upstream search return shapes."""
    if isinstance(resp, tuple):
        records = resp[0] if len(resp) >= 1 else []
        total = resp[1] if len(resp) > 1 else None
        return records, total

    if hasattr(resp, "records"):
        return getattr(resp, "records"), getattr(resp, "total", None)

    try:
        return list(resp), None
    except TypeError:
        raise TypeError("cannot unpack non-iterable search response")


class LennyDataProvider(OpenLibraryDataProvider):
    """Adapts Open Library metadata for Lenny's local catalog."""

    @staticmethod
    def search(
        query: str,
        numfound: int,
        limit: int,
        offset: int,
        lenny_ids: Optional[Mapping[int, int]] = None,
        encryption_map: Optional[Mapping[int, bool]] = None,
        base_url: Optional[str] = None,
    ) -> Tuple[List[LennyDataRecord], int]:
        """Perform a metadata search and adapt results into LennyDataRecords."""
        resp = OpenLibraryDataProvider.search(query=query, limit=limit, offset=offset)

        if isinstance(resp, DataProvider):
            ol_records = resp.records or []
            total = getattr(resp, "total", None)
        else:
            ol_records, total = _unwrap_search_response(resp)

        lenny_records: List[LennyDataRecord] = []

        # Convert keys to a predictable list order for mapping
        if isinstance(lenny_ids, Mapping):
            keys = list(lenny_ids.keys())
            values = list(lenny_ids.values())

            def _looks_like_index_sequence(seq: List[int]) -> bool:
                if not seq or not all(isinstance(item, int) for item in seq):
                    return False
                return seq == list(range(len(seq))) or seq == list(range(1, len(seq) + 1))

            keys_are_indices = _looks_like_index_sequence(keys)
            values_are_indices = _looks_like_index_sequence(values)

            if values and not values_are_indices:
                lenny_id_values = values
            elif keys and not keys_are_indices:
                lenny_id_values = keys
            elif values and not keys:
                lenny_id_values = values
            elif keys:
                lenny_id_values = keys
            else:
                lenny_id_values = []
        elif isinstance(lenny_ids, Iterable) and not isinstance(lenny_ids, (str, bytes)):
            lenny_id_values = list(lenny_ids)
        else:
            lenny_id_values = []

        for idx, record in enumerate(ol_records):
            data = record.model_dump()

            # Assign lenny_id properly from mapping keys
            if idx < len(lenny_id_values):
                data["lenny_id"] = lenny_id_values[idx]

            # Look up encryption status for this specific lenny_id
            lenny_id = data.get("lenny_id")
            if encryption_map and lenny_id is not None:
                data["is_encrypted"] = encryption_map.get(lenny_id, False)
            else:
                data["is_encrypted"] = False
            print("is_encrypted for record idx", idx, "lenny_id", lenny_id, ":", data["is_encrypted"])
            data["base_url"] = base_url
            lenny_records.append(LennyDataRecord.model_validate(data))
            
        return lenny_records, (total if total is not None else numfound)