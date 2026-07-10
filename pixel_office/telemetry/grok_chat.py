"""Grok chat_history.jsonl line -> (kind, ts, session_id, meta) | None.

Format verified 2026-07-10: flat records {"type": system|user|reasoning|
assistant, ...} with NO timestamps — the tailer substitutes the file's mtime
(= last-write time, exactly the last-activity signal liveness needs). Session
identity = the per-session directory (tailer fallback: file stem is
'chat_history'