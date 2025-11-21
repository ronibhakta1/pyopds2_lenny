from typing import List, Tuple, Optional, cast
from collections.abc import Mapping, Iterable
from pyopds2_openlibrary import OpenLibraryDataProvider, OpenLibraryDataRecord, Link
from pyopds2.provider import DataProvider, DataProviderRecord


class LennyDataRecord(OpenLibraryDataRecord):
    """Extends OpenLibraryDataRecord with local borrow/return links for Lenny."""

    lenny_id: Optional[int] = None
    is_encrypted: bool = False
    first_publish_year: Optional[int] = None
    publisher: Optional[list[str]] = None

    @property
    def type(self) -> str:
        return "http://schema.org/Book"
    
    def metadata(self):
        """Override to include additional fields like published date."""
        from datetime import datetime
        from pyopds2.models import Contributor
        
        metadata = super().metadata()
        
        if self.first_publish_year:
            try:
                metadata.published = datetime(self.first_publish_year, 1, 1)
            except:
                pass
        
        if self.publisher and len(self.publisher) > 0:
            metadata.publisher = [
                Contributor(
                    name=pub,
                    identifier=None,
                    sortAs=None,
                    role=None,
                    links=None,
                )
                for pub in self.publisher
            ]
        
        if hasattr(self, 'description') and self.description:
            if isinstance(self.description, dict):
                metadata.description = self.description.get('value', str(self.description))
            elif isinstance(self.description, str):
                metadata.description = self.description
        
        return metadata
    
    def to_publication(self):
        """Override to add @context for Readium Web Publication Manifest."""
        pub = super().to_publication()
        pub_dict = pub.model_dump()
        pub_dict["@context"] = "https://readium.org/webpub-manifest/context.jsonld"
        return type(pub)(**pub_dict)

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
            lenny_links.append(
                Link(
                    href=f"{base_uri}/borrow",
                    rel="http://opds-spec.org/acquisition/borrow",
                    type="application/opds-publication+json",
                    title="Lenny",
                    templated=False,
                    properties={
                        "availability": {
                            "state": "available"
                        },
                        "authenticate": {
                            "href": f"{LennyDataProvider.BASE_URL}authenticate",
                            "type": "application/opds-authentication+json"
                        },
                        "indirectAcquisition": [
                            {
                                "type": "application/vnd.readium.lcp.license.v1.0+json",
                                "child": [
                                    {"type": "application/epub+zip"}
                                ]
                            }
                        ]
                    },
                )
            )
        else:
            lenny_links.append(
                Link(
                    href=f"{base_uri}/read",
                    rel="http://opds-spec.org/acquisition/open-access",
                    type="application/opds-publication+json",
                    title="Read",
                    templated=False,
                    properties=None,
                )
            )
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


class LennyDataProvider(OpenLibraryDataProvider):
    """Adapts Open Library metadata for Lenny's local catalog."""

    @staticmethod
    def search(
        query: str,
        limit: int = 50,
        offset: int = 0,
        lenny_ids: Optional[Mapping[int, int]] = None,
        encryption_map: Optional[Mapping[int, bool]] = None,
    ) -> DataProvider.SearchResponse:
        """Perform a metadata search and adapt results into LennyDataRecords."""
        resp = OpenLibraryDataProvider.search(query=query, limit=limit, offset=offset)

        lenny_records: List[LennyDataRecord] = []
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

        for idx, record in enumerate(resp.records):
            data = record.model_dump()

            if idx < len(lenny_id_values):
                data["lenny_id"] = lenny_id_values[idx]

            lenny_id = data.get("lenny_id")
            if encryption_map and lenny_id is not None:
                data["is_encrypted"] = encryption_map.get(lenny_id, False)
            else:
                data["is_encrypted"] = False
            lenny_records.append(LennyDataRecord.model_validate(data))
            
        return DataProvider.SearchResponse(
            provider=LennyDataProvider,
            records=cast(List[DataProviderRecord], lenny_records),
            total=resp.total,
            query=resp.query,
            limit=resp.limit,
            offset=resp.offset,
            sort=resp.sort,
        )