"""External competitor #5: LlamaIndex — the 'build it yourself' standard RAG.

LlamaIndex VectorStoreIndex over the same 54-note vault, with the SAME Gemini
embedding model (via an adapter around Lemory's batched, rate-limited client),
its own default chunking (SentenceSplitter) and retrieval (cosine top-k).
This is what most teams assemble first when they 'add RAG' — the fairest
representative of the framework path.

Shared metrics with BENCHMARKS §4: answer-in-context@8 and full-support@8 on
LemoryBench (57 questions), plus p50 retrieval latency.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, WORK, load_env, normalize_answer, save_json

from lemory.providers.gemini import GeminiClient


def build_index(vault: Path):
    from llama_index.core import Settings, SimpleDirectoryReader, VectorStoreIndex
    from llama_index.core.embeddings import BaseEmbedding

    client = GeminiClient(api_key=os.environ["GEMINI_API_KEY"])

    class GeminiAdapter(BaseEmbedding):
        """Same gemini-embedding-001 @768d every other row uses."""

        model_config = {"arbitrary_types_allowed": True}

        def _get_query_embedding(self, query: str) -> list[float]:
            return client.embed([query], task_type="RETRIEVAL_QUERY")[0].tolist()

        def _get_text_embedding(self, text: str) -> list[float]:
            return client.embed([text])[0].tolist()

        def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
            return client.embed(texts).tolist()

        async def _aget_query_embedding(self, query: str) -> list[float]:
            return self._get_query_embedding(query)

        async def _aget_text_embedding(self, text: str) -> list[float]:
            return self._get_text_embedding(text)

    Settings.embed_model = GeminiAdapter()
    Settings.llm = None  # retrieval benchmark only

    docs = SimpleDirectoryReader(str(vault), required_exts=[".md"]).load_data()
    t0 = time.time()
    index = VectorStoreIndex.from_documents(docs)
    print(f"llamaindex ingest: {len(docs)} docs in {time.time()-t0:.1f}s", flush=True)
    return index


def main() -> None:
    load_env()
    vault = DATA / "multihop" / "vault"
    questions = json.loads((DATA / "multihop" / "questions.json").read_text())

    index = build_index(vault)
    retriever = index.as_retriever(similarity_top_k=8)

    aic, support, lat = [], [], []
    by_hops: dict[int, list[float]] = {1: [], 2: []}
    for q in questions:
        t0 = time.perf_counter()
        nodes = retriever.retrieve(q["q"])
        lat.append(time.perf_counter() - t0)
        texts = [n.get_content() for n in nodes]
        titles = {Path(n.metadata.get("file_name", "")).stem for n in nodes}
        hit = float(any(
            normalize_answer(a) in normalize_answer(t)
            for a in q["answers"] for t in texts
        ))
        aic.append(hit)
        by_hops[q["hops"]].append(hit)
        found = titles & set(q["gold_notes"])
        support.append(len(found) >= len(q["gold_notes"]))

    out = {
        "answer_in_context@8": sum(aic) / len(aic),
        "aic_1hop": sum(by_hops[1]) / len(by_hops[1]),
        "aic_2hop": sum(by_hops[2]) / len(by_hops[2]),
        "full_support@8": sum(support) / len(support),
        "p50_latency_ms": statistics.median(lat) * 1000,
        "n": len(questions),
        "note": "llama-index-core VectorStoreIndex, default SentenceSplitter, "
                "same gemini-embedding-001@768d as all other rows",
    }
    save_json(WORK / "results_llamaindex.json", out)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
