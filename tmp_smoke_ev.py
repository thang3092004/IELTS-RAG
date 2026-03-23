import sys
import types
import asyncio
import importlib.util
from pathlib import Path

# Stub missing external deps for smoke test
sys.modules.setdefault("ollama", types.SimpleNamespace(AsyncClient=lambda *a, **k: None))

# Load formatters and text_tools directly without importing package __init__
ROOT = Path(__file__).resolve().parent
sys.modules["videorag"] = types.ModuleType("videorag")
sys.modules["videorag.tools"] = types.ModuleType("videorag.tools")
sys.modules["videorag.debate"] = types.ModuleType("videorag.debate")
sys.modules["videorag.prompt"] = types.SimpleNamespace(GRAPH_FIELD_SEP="|")
# Minimal logger stub used by text_tools
class _StubLogger:
    def debug(self, msg):
        print(msg)

sys.modules["videorag._utils"] = types.SimpleNamespace(logger=_StubLogger())

# Preload evidence_types to satisfy formatters relative import without hitting videorag.__init__
ev_path = ROOT / "videorag" / "debate" / "evidence_types.py"
ev_spec = importlib.util.spec_from_file_location("videorag.debate.evidence_types", ev_path)
ev_mod = importlib.util.module_from_spec(ev_spec)
assert ev_spec and ev_spec.loader
ev_spec.loader.exec_module(ev_mod)
sys.modules["videorag.debate.evidence_types"] = ev_mod

fmt_path = ROOT / "videorag" / "tools" / "formatters.py"
fmt_spec = importlib.util.spec_from_file_location("videorag.tools.formatters", fmt_path)
fmt_mod = importlib.util.module_from_spec(fmt_spec)
assert fmt_spec and fmt_spec.loader
fmt_spec.loader.exec_module(fmt_mod)
sys.modules["videorag.tools.formatters"] = fmt_mod

text_tools_path = ROOT / "videorag" / "tools" / "text_tools.py"
txt_spec = importlib.util.spec_from_file_location("videorag.tools.text_tools", text_tools_path)
text_tools = importlib.util.module_from_spec(txt_spec)
assert txt_spec and txt_spec.loader
txt_spec.loader.exec_module(text_tools)
search_text_evidence = text_tools.search_text_evidence

class FakeVDB:
    async def query(self, query, top_k=6):
        return [{"id": "chunk1", "similarity": 0.9}, {"id": "chunk2", "distance": 0.2}]

class FakeText:
    _data = {
        "chunk1": {"content": "Alpha beta gamma"},
        "chunk2": {"content": "Delta epsilon zeta"},
    }
    async def get_by_ids(self, ids):
        return [self._data.get(i) for i in ids]

class FakeEntVDB:
    async def query(self, query, top_k=6):
        return [{"entity_name": "FOO", "similarity": 0.8}]

class FakeGraph:
    async def get_node(self, name):
        return {"description": "Foo entity", "source_id": "vidA_0|vidA_1"}

class FakeVideoSegs:
    _data = {
        "vidA": {
            "0": {"content": "cap0", "time": "0-10", "transcript": "t0"},
            "1": {"content": "cap1", "time": "10-20", "transcript": "t1"},
        }
    }

async def main():
    stores = {
        "chunks_vdb": FakeVDB(),
        "text_chunks": FakeText(),
        "entities_vdb": FakeEntVDB(),
        "knowledge_graph": FakeGraph(),
        "video_segments": FakeVideoSegs(),
    }
    ev = await search_text_evidence("test query", stores, top_k=2, entity_boost=True)
    for e in ev:
        print(e)

if __name__ == "__main__":
    asyncio.run(main())
