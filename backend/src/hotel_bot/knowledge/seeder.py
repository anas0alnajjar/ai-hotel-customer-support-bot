"""Ensure-only MySQL seed for approved fictional-hotel knowledge revisions."""

import hashlib
from collections import Counter
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from hotel_bot.domain.knowledge.enums import KnowledgeStatus
from hotel_bot.knowledge.loader import LoadedKnowledgeDataset, load_knowledge_dataset
from hotel_bot.persistence.models import KnowledgeDocument, KnowledgeRevision

KNOWLEDGE_NAMESPACE = uuid5(
    NAMESPACE_URL, "https://example.invalid/nour-al-sham-grand/knowledge/v1"
)


def stable_knowledge_id(entity: str, key: str) -> UUID:
    return uuid5(KNOWLEDGE_NAMESPACE, f"{entity}:{key}")


@dataclass(frozen=True, slots=True)
class KnowledgeSeedResult:
    dataset_version: str
    inserted: dict[str, int]
    existing: dict[str, int]


class KnowledgeSeeder:
    """Creates missing seed rows and never overwrites later administrator changes."""

    def __init__(self, session: AsyncSession, loaded: LoadedKnowledgeDataset | None = None) -> None:
        self._session = session
        self._loaded = loaded or load_knowledge_dataset()

    async def seed(self) -> KnowledgeSeedResult:
        inserted: Counter[str] = Counter()
        existing: Counter[str] = Counter()
        for item in self._loaded.dataset.documents:
            document_id = stable_knowledge_id("document", item.key)
            revision_id = stable_knowledge_id("revision", f"{item.key}:1")
            document = await self._session.get(KnowledgeDocument, document_id)
            if document is not None:
                existing["knowledge_documents"] += 1
                continue
            document = KnowledgeDocument(
                id=document_id,
                title=item.title,
                language=item.language,
                source_format=item.source_format.value,
                status=KnowledgeStatus.DRAFT,
            )
            self._session.add(document)
            await self._session.flush()
            revision = KnowledgeRevision(
                id=revision_id,
                document_id=document_id,
                content=item.content,
                checksum=self._content_checksum(item.content),
                version=1,
                created_by=None,
            )
            self._session.add(revision)
            await self._session.flush()
            document.current_revision_id = revision_id
            document.status = KnowledgeStatus.APPROVED
            inserted["knowledge_documents"] += 1
            inserted["knowledge_revisions"] += 1
        await self._session.flush()
        return KnowledgeSeedResult(
            dataset_version=self._loaded.dataset.dataset_version,
            inserted=dict(inserted),
            existing=dict(existing),
        )

    @staticmethod
    def _content_checksum(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
