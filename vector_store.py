import uuid
from qdrant_client import QdrantClient, models
import config


qdrant_client = QdrantClient(":memory:")

# qdrant_client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)

def get_or_create_collection(collection_name: str, vector_size: int):
    """
    Ensures a Qdrant collection exists. If not, it creates one.

    Args:
        collection_name: The name of the collection.
        vector_size: The dimensionality of the vectors that will be stored.
    """
    try:
        qdrant_client.get_collection(collection_name=collection_name)
        print(f"Collection '{collection_name}' already exists.")
    except Exception:
        print(f"Collection '{collection_name}' not found. Creating new collection.")
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=vector_size, distance=models.Distance.COSINE
            ),
        )
        print(f"Collection '{collection_name}' created successfully.")


def upsert_document(collection_name: str, vector: list[float], payload: dict):
    """
    Upserts a document (vector and payload) into the specified collection.

    Args:
        collection_name: The name of the collection.
        vector: The embedding vector of the document.
        payload: The metadata associated with the document.
    """
    point_id = str(uuid.uuid4())
    qdrant_client.upsert(
        collection_name=collection_name,
        points=[models.PointStruct(id=point_id, vector=vector, payload=payload)],
        wait=True,
    )
    print(f"Upserted document with ID {point_id} into '{collection_name}'.")
    return point_id


def search_similar(
    collection_name: str, query_vector: list[float], limit: int = 5
) -> list[models.ScoredPoint]:
    """
    Searches for vectors in the collection that are similar to the query vector.

    Args:
        collection_name: The name of the collection.
        query_vector: The vector to search with.
        limit: The maximum number of results to return.

    Returns:
        A list of ScoredPoint objects representing the search results.
    """
    search_result = qdrant_client.search(
        collection_name=collection_name, query_vector=query_vector, limit=limit
    )
    print(f"Found {len(search_result)} similar documents in '{collection_name}'.")
    return search_result
