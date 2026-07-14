<!-- generated:start edge:secret-store→truth-data-volume -->
> **Not verified at the current commit** — source has changed since the last full sweep, or none has run. Treat this section as a snapshot and verify against source before relying on it.
# Interaction: Secret Store → Truth Data Volume

- **Participants:** `secret-store` → `truth-data-volume`
- **Transport:** `file I/O`
<!-- generated:end edge:secret-store→truth-data-volume -->

> _Drafted by Aether from source — not human-verified._

## Contract  (request/response shapes and invariants)

This is an **in-process function-call contract**, not a network API. `secretstore` consumes exactly one thing from `truth-data-volume`: the function `truth.store.data_dir()`.

- **`data_dir() -> pathlib.Path`** — returns the mounted data volume directory (`$DATA_DIR`, default `./data`), creating it (`mkdir(parents=True, exist_ok=True)`) as a side effect. It never returns `None`; the directory is guaranteed to exist on return.
- `secretstore` uses only that path, appending a fixed filename: `secrets_path()` returns `data_dir() / "secrets.enc"`. It does **not** read/write `truth.yaml` or `truth.meta.yaml`, so it never touches `truth`'s own data files — the two share only the containing directory.

Invariants:
- The dependency is strictly one-directional: `secretstore` imports `truth.store`; `truth` has **no** reference to `secretstore` (verified by search — zero matches). This is deliberate: `secretstore` is described as a leaf that "imports only `truth.store` for the data path," letting both `api` and `providers` depend downward on it and breaking the project's only import cycle.
- `secretstore` writes its own file (`secrets.enc`) atomically (`.enc.tmp` then `replace`), the same atomic-write discipline `truth.store.save` uses for `truth.yaml` — so concurrent writers to the shared directory don't corrupt each other's files.
- The blob at `secrets.enc` is Fernet-encrypted JSON restricted to the whitelist `_FIELDS = ("activeProvider", "anthropicApiKey", "openaiApiKey", "ollamaHost", "model")`. Unknown keys and `None` values are stripped on write.
- Failure semantics are fail-soft on read: a missing, corrupt, or foreign blob is treated as absent (`read_secrets()` returns `{}`). Writes fail-hard: `write_secrets()` raises `SecretsUnavailable` if `ENCRYPTION_KEY` is missing/invalid.

## Auth  (how the interaction is authenticated)

The `secretstore` → `truth-data-volume` call itself is **unauthenticated** — it is a direct Python import and function call within the same process; there is no token, session, or transport auth on `data_dir()`.

The authentication that *is* present belongs to `secretstore` and is layered on top of the shared path:
- Access to the contents of `secrets.enc` is gated by the **`ENCRYPTION_KEY`** environment variable, used as a Fernet symmetric key. Without a valid key, `_fernet()` returns `None`, `encryption_available()` is `False`, reads yield `{}`, and writes raise `SecretsUnavailable`.
- File-system permissions on the mounted volume (`$DATA_DIR`) are the only boundary protecting the encrypted blob at rest; `truth.store` provides no additional gatekeeping.

## Flow  (the sequence of the interaction)

1. A caller (api or providers layer) invokes a `secretstore` function — e.g. `resolve_credentials()`, `read_secrets()`, or `write_secrets()`.
2. `secretstore` computes the target path via `secrets_path()`, which calls into `truth.store.data_dir()`.
3. `data_dir()` reads `$DATA_DIR` (default `./data`), ensures the directory exists on disk, and returns the `Path`.
4. `secretstore` appends `secrets.enc` to that path.
5. Depending on the operation:
   - **Read:** if a Fernet key exists and the file is present, decrypt and JSON-parse it; on any failure return `{}`.
   - **Write:** if no valid key, raise `SecretsUnavailable`; otherwise encrypt the whitelisted fields and atomically persist (`secrets.enc.tmp` → `secrets.enc`).
6. `resolve_credentials()` overlays any stored secret values onto environment-derived defaults (secrets win where present) and returns the merged credential dict.

`truth-data-volume`'s only participation is step 3 — resolving and ensuring the shared directory. It performs no work specific to secrets.

## Code  (entry points on both sides, with file paths)

**`secret-store` side** — `secretstore/__init__.py`:
- `secrets_path()` — the single call site into `truth`; returns `data_dir() / "secrets.enc"` (`from truth.store import data_dir` is imported lazily inside the function).
- `read_secrets()` / `write_secrets(data)` — decrypt/encrypt the blob at that path.
- `resolve_credentials()` — public merge of stored secrets over env defaults.
- Supporting helpers: `encryption_key()`, `_fernet()`, `encryption_available()`, and the `SecretsUnavailable` exception.

**`truth-data-volume` side** — `truth/store.py`:
- `data_dir()` — the sole entry point consumed by `secretstore`; resolves `$DATA_DIR` (default `./data`) and creates it.
- (Not used by `secretstore`, but co-located in the same module/volume: `truth_path()`, `load()`, `save()`, `validate()`, and the source-hash helpers, which manage `truth.yaml`/`truth.meta.yaml`.)

The relationship is a single import edge: `secretstore/__init__.py:34` (`from truth.store import data_dir`) → `truth/store.py:data_dir`.
