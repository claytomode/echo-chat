"""Converts messages from knowledge_base.db into a Qdrant vector store."""

import sqlite3
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer
from fastembed import SparseTextEmbedding
from tqdm import tqdm
import os

# Import configurations from config.py
import dotenv

dotenv.load_dotenv()

from config import (
    QDRANT_URL,
    QDRANT_API_KEY,
    QDRANT_COLLECTION_NAME,
    SENTENCE_TRANSFORMER_MODEL_NAME,
    SPARSE_MODEL_NAME,
)


def upload_knowledge_base_to_qdrant(
    knowledge_base_db_path: str = 'knowledge_base.db',
    qdrant_url: str = 'localhost',
    qdrant_port: int | None = 6333,  # Not directly used if QDRANT_URL is full URL
    qdrant_grpc_port: int | None = 6334,  # Usually from Qdrant, can be defaulted
    collection_name: str = QDRANT_COLLECTION_NAME,  # From config
    sentence_transformer_model_name: str = SENTENCE_TRANSFORMER_MODEL_NAME,  # From config
    sparse_model_name: str = SPARSE_MODEL_NAME,  # From config
    batch_size: int = 256,
    sparse_batch_size: int = 16,
    *,
    recreate_collection: bool = True,
) -> None:
    """
    Reads messages from 'messages' table in knowledge_base.db,
    generates dense and sparse embeddings, and uploads them to Qdrant.
    """
    if not os.path.exists(knowledge_base_db_path):
        raise FileNotFoundError(f'Knowledge base DB not found at: {knowledge_base_db_path}')

    conn = sqlite3.connect(knowledge_base_db_path)
    cursor = conn.cursor()
    print(f'Connected to knowledge base database: {knowledge_base_db_path}')

    cursor.execute(
        'SELECT id, text, conversation_id, is_from_me, date_iso, timestamp_seconds FROM messages ORDER BY timestamp_seconds ASC'
    )
    messages_to_process = cursor.fetchall()
    conn.close()
    print(f'Fetched {len(messages_to_process)} messages from knowledge_base.db.')

    if not messages_to_process:
        print('No messages found in knowledge_base.db to upload to Qdrant.')
        return

    # Load models (ensure CUDA is available if `cuda=True` is used)
    try:
        model = SentenceTransformer(
            sentence_transformer_model_name,
            device='cuda' if os.environ.get('USE_CUDA') == 'true' else 'cpu',
        )
        print('Dense embedding model loaded.')
    except Exception as e:
        print(f'Could not load SentenceTransformer model on CUDA, trying CPU: {e}')
        model = SentenceTransformer(sentence_transformer_model_name, device='cpu')

    try:
        sparse_model = SparseTextEmbedding(
            model_name=sparse_model_name,
            cuda=True if os.environ.get('USE_CUDA') == 'true' else False,
        )
        print('Sparse embedding model loaded.')
    except Exception as e:
        print(f'Could not load SparseTextEmbedding model on CUDA, trying CPU: {e}')
        sparse_model = SparseTextEmbedding(model_name=sparse_model_name, cuda=False)

    client = QdrantClient(
        url=qdrant_url, port=qdrant_port, grpc_port=qdrant_grpc_port, api_key=QDRANT_API_KEY
    )
    print(f'Connected to Qdrant client at {QDRANT_URL}.')

    # Define vector parameters
    sparse_vector_params = models.SparseVectorParams(index=models.SparseIndexParams(on_disk=False))
    hnsw_config_initial = models.HnswConfigDiff(m=0)  # Temporarily disable HNSW for faster upsert
    dense_vector_params = models.VectorParams(
        size=model.get_sentence_embedding_dimension() or 0,  # Ensure size is not None
        distance=models.Distance.COSINE,
        hnsw_config=hnsw_config_initial,
        on_disk=True,
    )

    # Collection management
    if recreate_collection:
        if client.collection_exists(collection_name):
            client.delete_collection(collection_name=collection_name)
            print(f"Existing collection '{collection_name}' deleted.")
        client.create_collection(
            collection_name=collection_name,
            vectors_config={'dense': dense_vector_params},
            sparse_vectors_config={'sparse': sparse_vector_params},
        )
        print(f"Collection '{collection_name}' created/initialized.")
    elif not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config={'dense': dense_vector_params},
            sparse_vectors_config={'sparse': sparse_vector_params},
        )
        print(f"Collection '{collection_name}' created/initialized.")
    else:
        print(f"Collection '{collection_name}' already exists. Appending data.")

    total_messages = len(messages_to_process)
    print(
        f'Starting embedding and upsert for {total_messages} messages in batches of {batch_size} '
        f'(dense/upsert) and sub-batches of {sparse_batch_size} (sparse).'
    )

    for i in tqdm(range(0, total_messages, batch_size), desc='Ingesting messages to Qdrant'):
        batch_raw_messages = messages_to_process[i : i + batch_size]

        # Extract text for batch processing
        batch_texts = [msg[1] for msg in batch_raw_messages]  # msg[1] is 'text'

        # Generate dense embeddings
        batch_embeddings = model.encode(batch_texts).tolist()

        # Generate sparse embeddings in sub-batches
        all_sparse_embeddings_in_batch = []
        for j in range(0, len(batch_texts), sparse_batch_size):
            sub_batch_texts = batch_texts[j : j + sparse_batch_size]
            all_sparse_embeddings_in_batch.extend(list(sparse_model.embed(sub_batch_texts)))

        points_to_upsert = []
        for j, msg_data_tuple in enumerate(batch_raw_messages):
            # Unpack the tuple: id, text, conversation_id, is_from_me, date_iso, timestamp_seconds
            msg_id, text, conversation_id, is_from_me, date_iso, timestamp_seconds = msg_data_tuple

            dense_vector = batch_embeddings[j]
            sparse_embedding = all_sparse_embeddings_in_batch[j]

            payload = {
                'text': text,
                'conversation_id': conversation_id,
                'is_from_me': bool(is_from_me),
                'date': date_iso,
                'timestamp_seconds': timestamp_seconds,
            }

            sparse_vector = models.SparseVector(
                indices=sparse_embedding.indices.tolist(),
                values=sparse_embedding.values.tolist(),
            )

            points_to_upsert.append(
                models.PointStruct(
                    id=msg_id,  # Use the ID from knowledge_base.db as the Qdrant point ID
                    payload=payload,
                    vector={
                        'dense': dense_vector,
                        'sparse': sparse_vector,
                    },
                ),
            )

        if points_to_upsert:
            client.upsert(collection_name=collection_name, points=points_to_upsert, wait=True)

    print('\nMessage ingestion to Qdrant complete.')

    print(f"Re-enabling HNSW indexing for '{collection_name}'...")
    client.update_collection(
        collection_name=collection_name,
        vectors_config={
            'dense': models.VectorParamsDiff(
                hnsw_config=models.HnswConfigDiff(
                    m=16,
                    ef_construct=100,
                ),
            ),
        },
    )
    print(
        f"HNSW indexing re-enabled for '{collection_name}'. "
        'Qdrant will now build the index in background.'
    )


if __name__ == '__main__':
    try:
        upload_knowledge_base_to_qdrant(
            knowledge_base_db_path='knowledge_base.db',
            recreate_collection=True,  # Set to False if you want to append to an existing Qdrant collection
        )
    except FileNotFoundError as e:
        print(f"Error: {e}. Please ensure 'sms_to_knowledge_base.py' has been run successfully.")
    except Exception as e:
        print(f'An unexpected error occurred during Qdrant upload: {e}')
