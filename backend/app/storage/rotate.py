"""Key rotation and first-time encryption: `python -m app.storage.rotate`.

Walks every document's blob and brings it to the active key: unencrypted uploads are encrypted, objects wrapped by a
retired key get their data key re-wrapped (the file contents are not re-encrypted), current ones are left alone.
Safe to re-run, and safe to interrupt. Prints counts only: no key material, no blob keys, no file names.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter

from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import make_engine
from app.models.tables import Document
from app.storage.base import build_blob_store
from app.storage.vault import VaultBlobStore, VaultError


async def rotate_all(store: VaultBlobStore, blob_keys: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for blob_key in blob_keys:
        try:
            counts[await store.rewrap(blob_key)] += 1
        except VaultError:
            counts["failed"] += 1  # the vault already logged the reason for this object
        except FileNotFoundError:
            counts["missing"] += 1
        except OSError:
            counts["failed"] += 1
    return counts


async def run(settings: Settings) -> int:
    if not settings.vault_enabled:
        print("VAULT_ENABLED is false: nothing to rotate.", file=sys.stderr)
        return 2
    store = build_blob_store(settings)
    if not isinstance(store, VaultBlobStore):  # pragma: no cover - build_blob_store wraps whenever the vault is on
        return 2
    engine = make_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            blob_keys = list((await conn.execute(select(Document.blob_key))).scalars())
    finally:
        await engine.dispose()
    counts = await rotate_all(store, blob_keys)
    print(
        f"key {store.key_id}: {len(blob_keys)} objects, {counts['encrypted']} encrypted, "
        f"{counts['rewrapped']} rewrapped, {counts['current']} already current, "
        f"{counts['missing']} missing, {counts['failed']} failed"
    )
    return 1 if counts["failed"] else 0


def main() -> None:
    try:
        code = asyncio.run(run(get_settings()))
    except VaultError as exc:  # a bad key setting: say which setting, never the key
        print(f"Vault error: {exc.detail}", file=sys.stderr)
        code = 2
    sys.exit(code)


if __name__ == "__main__":
    main()
