# Encrypted vault and OCR

Two optional features for deployments that hold real company files. Both are off by default and both work in [private mode](private-deployment.md): nothing here talks to the network.

## Encrypted vault

With `VAULT_ENABLED=true`, every uploaded file is encrypted before it reaches the disk volume or the S3 bucket (AES-256-GCM, envelope encryption). Each file gets its own random data key; that key is wrapped with your master key, and the master key's id is stored in the file so keys can be rotated. Anything that changes a stored file (a flipped bit, a truncated copy, one file renamed to another's name, an edited key id) makes the read fail with a 500 `vault_error`; it never returns garbage or silently falls back to the raw bytes.

### What it protects, and what it does not

| Protects | Does not protect |
|---|---|
| A stolen disk, a volume snapshot, a backup of `uploads`, an S3 bucket read by someone without the key | Anyone who can run commands on the API host or read its environment: the API holds the key to serve downloads |
| Files swapped or edited at rest (detected, not silently served) | **The database.** Chunk text, titles, filenames and embeddings are plain in Postgres, because search needs them. This feature protects the original *files* at rest, not the extracted text |
| | Memory, logs and the model server's disk |

Treat it as one layer. Pair it with disk encryption for the Postgres volume, and keep the key somewhere other than next to the files (a Docker or Kubernetes secret, a secrets manager). Putting the key in the same `.env` as everything else is better than nothing and weaker than a mounted secret.

### Setup

1. Generate a key (32 random bytes, base64):

   ```bash
   python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
   ```

2. Store it as a secret file and point the app at it (preferred over putting it in an environment variable, because environment variables show up in `docker inspect` and process listings):

   ```env
   VAULT_ENABLED=true
   VAULT_KEY_FILE=/run/secrets/vault_key      # file contents: the base64 (or 64 hex characters), whitespace is ignored
   VAULT_KEY_ID=k1                            # 1-64 characters from A-Z a-z 0-9 . _ -
   ```

   `VAULT_KEY=<key>` also works; if both are set the file wins. The app refuses to start when the vault is on and the key is missing, malformed (not exactly 32 bytes), or unreadable.

3. Files uploaded before you turned the vault on keep working: objects without the vault header are returned as they are. Encrypt them with the rotation command below.

### Rotating the key

```bash
# 1. Make a new key and give it a new id; keep the old one in a JSON file
echo '{"k1": "<old key>"}' > retired-keys.json
#    VAULT_KEY_FILE -> the new key, VAULT_KEY_ID=k2, VAULT_RETIRED_KEYS_FILE=/run/secrets/retired_keys.json
# 2. Restart the api and worker. New uploads use k2; old files still open through the retired key.
# 3. Re-wrap everything (also encrypts any pre-vault uploads). Safe to repeat or interrupt.
docker compose run --rm api python -m app.storage.rotate     # from backend/: uv run python -m app.storage.rotate
# key k2: 1204 objects, 3 encrypted, 1190 rewrapped, 11 already current, 0 missing, 0 failed
# 4. When it reports 0 failed, remove the retired key from the file and restart.
```

Rotation re-wraps a 48-byte data key per file; the file contents are not re-encrypted or re-uploaded, so it is quick even for large S3 buckets. The command prints counts only. A non-zero `failed` means some objects did not authenticate (wrong or missing retired key, or tampering); the reason per object is in the API log by blob key, never with key material. The exit code is 1 in that case.

### Backups and losing the key

**If you lose the key, you lose the files.** There is no recovery path and no backdoor. Back the key up separately from the data backups (a password manager, a sealed envelope, a secrets manager with its own backup), and back up retired keys until a rotation has finished. An uploaded file can be re-uploaded; the extracted text in Postgres stays searchable, but the citation viewer's original file would be gone.

Encrypted objects are bound to their storage key (`<collection>/<id>...`). Copying one to a different key by hand makes it unreadable on purpose. Restore backups under the same keys.

### Downgrade note

While plain objects are accepted (the default, so old uploads work), someone with write access to the volume could replace an encrypted file with a plain one and it would be served. After `python -m app.storage.rotate` reports everything encrypted, that gap is closed only if you also construct the store with `allow_plaintext=False`; it is a constructor option, not a setting, because turning it on before rotation would break old uploads.

## OCR for scanned PDFs

Without OCR, a PDF with no text layer is rejected with "The PDF has no extractable text (scanned PDFs need OCR, which is not supported)". With `OCR_ENABLED=true`, pages that have no usable text layer (fewer than 20 characters, and containing a picture or drawing) are read with Tesseract through PyMuPDF's built-in integration. Pages that already have text are never OCR'd, and blank pages are skipped. The OCR'd text goes through the same heading, table and chunking logic as normal text, so citations carry the right page number.

```env
OCR_ENABLED=true
OCR_LANGUAGES=eng          # Tesseract codes joined with +, e.g. eng+deu
OCR_DPI=300                # 72-600; higher is slower and a little more accurate on small print
OCR_MAX_PAGES=200          # per document
```

### Installing Tesseract

- **Docker:** `docker build -f backend/Dockerfile --build-arg WITH_OCR=true --build-arg OCR_LANGS="eng deu" .` installs `tesseract-ocr` plus `tesseract-ocr-<lang>` for each language and sets `TESSDATA_PREFIX`. The default image (`WITH_OCR=false`) is unchanged and does not contain Tesseract. With compose, pass the same values as build args on the `api` and `worker` services (the worker is the one that parses).
- **Windows / macOS / Linux dev machine:** install Tesseract from your package manager and make sure the language data folder is found (set `TESSDATA_PREFIX` to the `tessdata` folder if needed).

If `OCR_ENABLED=true` and Tesseract (or a configured language) is missing, a scanned document fails with a clear message ("OCR is enabled but Tesseract is not installed ...") instead of being half-indexed. Documents that have a text layer are unaffected, because Tesseract is only looked for when a scanned page turns up.

### Private mode

OCR is local: the page image is rendered and read inside the worker process, nothing is sent anywhere, and no model is involved. It is compatible with `PRIVATE_MODE=true` and `docker-compose.private.yml` with no network change.

### Limits

- **Quality depends on the scan.** Clean 300 dpi print reads well; skewed pages, small print, handwriting, stamps and low contrast produce wrong words. A misread word can then be quoted or cited wrongly, so verification (which checks quotes against the stored text) cannot catch an OCR error. Check important scans by eye and look at the passage in the citation viewer.
- **Speed.** Expect seconds per page on CPU, and a few seconds more at 400-600 dpi. Ingestion runs in the worker, so a large scan delays the queue behind it but never a request.
- **Page cap.** After `OCR_MAX_PAGES` OCR'd pages in one document the rest are skipped (pages with a text layer are still read). The document is rejected only if nothing could be read at all, with a message naming the cap. Raise it deliberately for long scans.
- **Layout.** Multi-column scans and tables are reconstructed from word positions and can come out in a different order than a human would read them.
- **Not for scans inside DOCX/HTML.** Only PDFs are OCR'd; pictures in other formats are ignored as before.
