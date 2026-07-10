"""One descriptor per CLI — the single place to add or update a CLI.

Adding a CLI = create `adapters/<cli>.py` defining an `ADAPTER`, then list it in
`registry.py`. Everything else (doctor's capability matrix, normalization, the
tailer's parser + session-id fallback, the conformance test, the SQLite mapper
registry) reads from the registry — no other file needs to change.

See `base.Adapter` for the fields and `registry` for the lookups.
"""
