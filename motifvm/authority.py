from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .storage import utc_now


ROOT = Path.cwd()


def authority_ref(
    authority_id: str,
    source_name: str,
    source_type: str,
    version: str,
    location: str,
    section_id: str,
    quoted_rule_excerpt: str,
    confidence: float = 0.8,
    effective_date: str | None = None,
) -> dict[str, Any]:
    source_path = location.split("#", 1)[0]
    return {
        "id": authority_id,
        "sourceName": source_name,
        "sourceType": source_type,
        "version": version,
        "effectiveDate": effective_date,
        "retrievedAt": utc_now(),
        "location": location,
        "sectionId": section_id,
        "quotedRuleExcerpt": quoted_rule_excerpt,
        "sourceHash": file_hash_if_exists(source_path),
        "sectionHash": hashlib.sha256(quoted_rule_excerpt.encode("utf-8")).hexdigest(),
        "confidence": confidence,
    }


def file_hash_if_exists(location: str) -> str | None:
    path = ROOT / location
    if not path.exists():
        path = Path(location)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
