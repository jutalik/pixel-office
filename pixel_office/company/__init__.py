"""The company operating layer — see docs/COMPANY-LAYER.md.

Built incrementally, cheapest value first. Each module is a small descriptor in
the same one-file-per-thing spirit as `adapters/`. Nothing here burns tokens by
itself; employee *reasoning* is a pluggable executor (deterministic in tests,
a real CLI agent in production) so the coordination logic is fully e2e-testable.
"""
