from config.settings import (
    QDRANT_API_KEY,
    QDRANT_COLLECTION_NAME,
    QDRANT_GRPC_PORT,
    QDRANT_HTTP_PORT,
    QDRANT_URL,
    SENTENCE_TRANSFORMER_MODEL_NAME,
    SPARSE_MODEL_NAME,
    USE_CUDA,
)
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

dense_model = SentenceTransformer(
    SENTENCE_TRANSFORMER_MODEL_NAME,
    device='cuda' if USE_CUDA else 'cpu',
)
sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME, cuda=USE_CUDA)

client = QdrantClient(
    url=QDRANT_URL, port=QDRANT_HTTP_PORT, grpc_port=QDRANT_GRPC_PORT, api_key=QDRANT_API_KEY
)


def similarity_search(text: str, limit: int):
    dense_vector = dense_model.encode(text).tolist()
    dense_prefetch = models.Prefetch(
        query=dense_vector,
        using='dense',
        limit=limit,
    )

    sparse_embedding = next(iter(sparse_model.embed([text])))
    sparse_vector = models.SparseVector(
        indices=sparse_embedding.indices.tolist(),
        values=sparse_embedding.values.tolist(),
    )
    sparse_prefetch = models.Prefetch(
        query=sparse_vector,
        using='sparse',
        limit=limit,
    )

    return client.query_points(
        collection_name=QDRANT_COLLECTION_NAME,
        prefetch=[dense_prefetch, sparse_prefetch],
        limit=limit,
        with_payload=True,
    )
