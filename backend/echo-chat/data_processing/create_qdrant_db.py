
"""Upsert vectorized messages to Qdrant."""
import sqlite3
import uuid
from pathlib import Path

from qdrant_client import models
from tqdm import tqdm

from config.settings import QDRANT_COLLECTION_NAME
from core.models import Message
from core.vector_store import client, dense_model, sparse_model


def upload_knowledge_base_to_qdrant(
    knowledge_base_db_path: str = 'knowledge_base.db',
    collection_name: str = QDRANT_COLLECTION_NAME,
    batch_size: int = 256,
    sparse_batch_size: int = 16,
    *,
    recreate_collection: bool = True,
) -> None:
    """Upload messages from a SQLite knowledge base to Qdrant.

    Args:
        knowledge_base_db_path: Path to the SQLite database containing messages.
        collection_name: Name of the Qdrant collection to upload to.
        batch_size: Number of messages to process in each batch for dense embeddings.
        sparse_batch_size: Number of messages to process in each sub-batch for sparse embeddings.
        recreate_collection: If True, deletes and recreates the collection before
                             uploading. Defaults to True.

    """
    if not Path(knowledge_base_db_path).exists():
        msg = f'Database not found: {knowledge_base_db_path}'
        raise FileNotFoundError(msg)

    with sqlite3.connect(knowledge_base_db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, text, conversation_id, is_from_me, date_iso, timestamp_seconds '
            'FROM messages ORDER BY timestamp_seconds ASC'
        )
        messages = cursor.fetchall()

    if not messages:
        print('No messages to ingest.')
        return
    print(f'Fetched {len(messages)} messages from the database.')

    if recreate_collection and client.collection_exists(collection_name):
        print(f"Deleting existing collection '{collection_name}'...")
        client.delete_collection(collection_name=collection_name)

    if not client.collection_exists(collection_name):
        print(f"Creating new collection '{collection_name}'...")
        dense_vector_size = dense_model.get_sentence_embedding_dimension() or 0
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                'dense': models.VectorParams(
                    size=dense_vector_size, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                'sparse': models.SparseVectorParams(index=models.SparseIndexParams(on_disk=False))
            },
        )

    print(f'Starting ingestion in batches of {batch_size} (sparse sub-batches of {sparse_batch_size})...')
    for i in tqdm(range(0, len(messages), batch_size), desc='Ingesting to Qdrant'):
        batch_messages = [Message(**msg) for msg in messages[i : i + batch_size]]
        batch_texts = [msg.text for msg in batch_messages]

        batch_dense_embeddings = dense_model.encode(batch_texts)

        all_sparse_embeddings = []
        for j in range(0, len(batch_texts), sparse_batch_size):
            sub_batch_texts = batch_texts[j : j + sparse_batch_size]
            all_sparse_embeddings.extend(list(sparse_model.embed(sub_batch_texts)))

        points = [
            models.PointStruct(
                id=msg.id or str(uuid.uuid4()),
                payload=msg.model_dump(exclude={'id'}),
                vector={
                    'dense': batch_dense_embeddings[idx].tolist(),
                    'sparse': models.SparseVector(
                        indices=sparse.indices.tolist(), values=sparse.values.tolist()
                    ),
                },
            )
            for idx, (msg, sparse) in enumerate(
                zip(batch_messages, all_sparse_embeddings, strict=True)
            )
        ]

        if points:
            client.upsert(collection_name=collection_name, points=points, wait=True)

    print('\nIngestion process finished successfully.')
