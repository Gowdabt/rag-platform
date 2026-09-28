from __future__ import annotations

from app.domain.types import ConnectorFile, DocumentChange


def diff_connector_files(previous: list[ConnectorFile], current: list[ConnectorFile]) -> list[DocumentChange]:
    """Compare snapshots using stable source_file_id, never filename."""
    prev = {f.source_file_id: f for f in previous}
    curr = {f.source_file_id: f for f in current}
    changes: list[DocumentChange] = []
    for fid, file in curr.items():
        old = prev.get(fid)
        if old is None:
            changes.append(DocumentChange(event_type="DOCUMENT_CREATED", file=file))
            continue
        moved = (old.path or "") != (file.path or "")
        updated = (old.checksum or old.revision or old.etag) != (file.checksum or file.revision or file.etag)
        if moved and not updated:
            changes.append(DocumentChange(event_type="DOCUMENT_MOVED", file=file))
        elif updated:
            changes.append(DocumentChange(event_type="DOCUMENT_UPDATED", file=file))
    for fid, file in prev.items():
        if fid not in curr:
            changes.append(DocumentChange(event_type="DOCUMENT_DELETED", file=file))
    return changes
