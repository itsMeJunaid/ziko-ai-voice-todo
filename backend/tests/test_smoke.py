"""Phase 0 smoke test: the toolchain runs. Real tests arrive in Phase 1."""


def test_imports() -> None:
    import google.genai  # noqa: F401
    import pvporcupine  # noqa: F401
    import sqlalchemy  # noqa: F401
