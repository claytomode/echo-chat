import config
import vector_store

from openai import OpenAI

client = OpenAI(
    api_key=config.API_KEY,
    base_url=config.BASE_URL,
)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_VECTOR_SIZE = 1536


def get_embedding(text: str) -> list[float]:
    """generates an embedding for the given text using the configured model."""
    text = text.replace("\n", " ")
    response = client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
    return response.data[0].embedding


def main():
    """a demonstration of integrating qdrant with the openai client."""
    print("--- qdrant integration example ---")

    vector_store.get_or_create_collection(
        collection_name=config.QDRANT_COLLECTION_NAME,
        vector_size=EMBEDDING_VECTOR_SIZE,
    )

    documents = [
        {"text": "the qdrant vector database is written in rust.", "source": "qdrant docs"},
        {"text": "fastapi is a modern, fast web framework for building apis.", "source": "fastapi docs"},
        {"text": "the openai python sdk makes it easy to use their models.", "source": "openai docs"},
    ]

    print("\n--- upserting documents ---")
    for doc in documents:
        embedding = get_embedding(doc["text"])
        vector_store.upsert_document(
            collection_name=config.QDRANT_COLLECTION_NAME, vector=embedding, payload=doc
        )

    print("\n--- performing search ---")
    query = "what programming language is qdrant built with?"
    print(f"query: {query}")

    query_embedding = get_embedding(query)
    search_results = vector_store.search_similar(
        collection_name=config.QDRANT_COLLECTION_NAME, query_vector=query_embedding
    )

    print("\n--- search results ---")
    for result in search_results:
        print(f"score: {result.score:.4f} - payload: {result.payload}")


if __name__ == "__main__":
    main()
