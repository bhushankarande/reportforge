from tools.rag.bm25_store import BM25Store
from tools.rag.chunking import fixed_overlap_chunks
from tools.rag.hybrid_retriever import HybridRetriever
from tools.rag.vector_store import InMemoryVectorStore


def test_fixed_overlap_chunks_returns_overlapping_chunks():
    chunks = fixed_overlap_chunks("abcdefghijklmnopqrstuvwxyz", chunk_size=10, overlap=2)

    assert chunks[0] == "abcdefghij"
    assert chunks[1].startswith("ij")


def test_hybrid_retriever_returns_indexed_text():
    vector_store = InMemoryVectorStore("job-1")
    bm25_store = BM25Store()
    vector_store.add_text("1", "market growth evidence", "source-1")
    bm25_store.add_text("1", "market growth evidence", "source-1")

    results = HybridRetriever(vector_store, bm25_store).search("market")

    assert results == ["market growth evidence"]


def test_hybrid_retriever_fuses_vector_and_bm25_results():
    vector_store = InMemoryVectorStore("job-2")
    bm25_store = BM25Store()
    vector_store.add_text("v1", "semantic revenue trend", "source-1")
    bm25_store.add_text("b1", "exact market demand", "source-2")

    results = HybridRetriever(vector_store, bm25_store).search("market demand")

    assert "exact market demand" in results
    assert len(results) == 2


def test_hybrid_retriever_retrieve_filters_by_source_type():
    retriever = HybridRetriever(job_id="job-3")
    retriever.add_documents(["uploaded evidence about revenue"], source_id="source-1", source_type="upload")
    retriever.add_documents(["web evidence about revenue"], source_id="source-2", source_type="web")

    results = retriever.retrieve("revenue", filters={"source_type": "upload"})

    assert results
    assert all(result.source_type == "upload" for result in results)
