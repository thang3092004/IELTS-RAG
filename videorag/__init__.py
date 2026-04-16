try:
    from .videorag import VideoRAG, QueryParam
except (ImportError, ModuleNotFoundError):
    # Allow subpackages (tvg, etc.) to be imported without the full
    # VideoRAG stack (transformers, tiktoken, etc.) — e.g. during unit tests.
    pass