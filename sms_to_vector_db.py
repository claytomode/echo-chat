import sqlite3
from datetime import datetime, timedelta

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer
from tqdm import tqdm


def assign_conversation_ids(messages: list, time_gap_threshold_minutes: int = 30) -> list:
    """Assign pseudo conversation IDs based on time gaps between messages.

    Messages MUST be sorted by 'timestamp_raw' ascending before calling this.
    """
    if not messages:
        return []

    processed_messages = []
    current_conversation_id = 0

    for i, msg in enumerate(messages):
        if i == 0:
            msg['conversation_id'] = f'conv_{current_conversation_id}'
            processed_messages.append(msg)
            continue

        prev_msg = processed_messages[i - 1]

        time_diff_seconds = msg['timestamp_raw'] - prev_msg['timestamp_raw']
        time_diff_minutes = time_diff_seconds / 60

        if time_diff_minutes > time_gap_threshold_minutes:
            current_conversation_id += 1

        msg['conversation_id'] = f'conv_{current_conversation_id}'
        processed_messages.append(msg)

    return processed_messages


def sms_db_to_qdrant(
    sms_db_path: str,
    target_phone_number: str,
    qdrant_host: str = 'localhost',
    qdrant_port: int = 6333,
    qdrant_grpc_port: int = 6334,
    collection_name: str = 'echo_chat',
    sentence_transformer_model_name: str = 'BAAI/bge-large-en-v1.5',
    conversation_gap_minutes: int = 30,
    batch_size: int = 256,
    *,
    recreate_collection: bool = True,
):
    conn = sqlite3.connect(sms_db_path)
    cursor = conn.cursor()
    print('connected to sms database.')
    query = """
            SELECT
                message.ROWID,
                message.text,
                message.is_from_me,
                message.date
            FROM
                message
            INNER JOIN
                handle ON message.handle_id = handle.ROWID
            WHERE
                REPLACE(REPLACE(REPLACE(handle.id, '+', ''), '-', ''), ' ', '') LIKE ?
            ORDER BY
                message.date ASC;
            """
    # simple processing to normalize
    normalized_phone_number = target_phone_number.replace('+', '').replace('-', '').replace(' ', '')
    cursor.execute(query, (f'%{normalized_phone_number}%',))
    raw_messages = cursor.fetchall()
    print(f'fetched {len(raw_messages)} raw messages.')
    if not raw_messages:
        conn.close()
        raise ValueError(f'no messages found for {target_phone_number} in {sms_db_path}')

    coredata_epoch = datetime(2001, 1, 1, tzinfo=None)
    processed_messages = []
    current_conversation_id = 0
    last_message_date = None

    for row_id, text, is_from_me, date_coredata in raw_messages:
        message_datetime = coredata_epoch + timedelta(seconds=date_coredata / 1_000_000_000)

        if last_message_date is None or (message_datetime - last_message_date).total_seconds() > (
            conversation_gap_minutes * 60
        ):
            current_conversation_id += 1

        processed_messages.append(
            {
                'id': row_id,
                'text': str(text) if text is not None else '',
                'is_from_me': bool(is_from_me),
                'date': message_datetime.isoformat(),
                'timestamp_seconds': date_coredata,
                'conversation_id': f'conv_{current_conversation_id}',
            }
        )
        last_message_date = message_datetime

    conn.close()
    print(f'processed {len(processed_messages)} messages and assigned conversation ids.')

    model = SentenceTransformer(sentence_transformer_model_name)
    print('sentence transformer model loaded.')

    client = QdrantClient(host=qdrant_host, port=qdrant_port, grpc_port=qdrant_grpc_port)
    print('connected to qdrant client.')

    dense_vector_params = models.VectorParams(
        size=model.get_sentence_embedding_dimension(), distance=models.Distance.COSINE
    )
    sparse_vector_params = models.SparseVectorParams()

    if recreate_collection:
        if client.collection_exists(collection_name):
            client.delete_collection(collection_name=collection_name)
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                'dense': dense_vector_params,
            },
            sparse_vectors_config={
                'sparse': sparse_vector_params,
            },
        )
        print(f"collection '{collection_name}' recreated/initialized.")
    elif not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                'dense': dense_vector_params,
            },
            sparse_vectors_config={
                'sparse': sparse_vector_params,
            },
        )
        print(f"collection '{collection_name}' created/initialized.")
    else:
        print(f"collection '{collection_name}' already exists. appending data.")

    total_messages = len(processed_messages)
    print(
        f'starting embedding and upsert for {total_messages} messages in batches of {batch_size}.'
    )

    for i in tqdm(range(0, total_messages, batch_size), desc='Ingesting messages to Qdrant'):
        batch_messages = processed_messages[i : i + batch_size]
        batch_texts = [msg['text'] for msg in batch_messages]

        batch_embeddings = model.encode(batch_texts).tolist()

        points_to_upsert = []
        for j, msg_data in enumerate(batch_messages):
            point_id = msg_data['id']
            dense_vector = batch_embeddings[j]

            payload = {
                'text': msg_data['text'],
                'conversation_id': msg_data['conversation_id'],
                'is_from_me': msg_data['is_from_me'],
                'date': msg_data['date'],
                'timestamp_seconds': msg_data['timestamp_seconds'],
            }

            points_to_upsert.append(
                models.PointStruct(
                    id=point_id,
                    payload=payload,
                    vector={
                        'dense': dense_vector,
                    },
                ),
            )

        client.upsert(collection_name=collection_name, points=points_to_upsert, wait=True)


if __name__ == '__main__':
    SMS_DB_PATH = ''
    HER_PHONE_NUMBER = ''

    QDRANT_HOST = 'localhost'
    QDRANT_PORT = 6333
    QDRANT_GRPC_PORT = 6334

    SENTENCE_TRANSFORMER_MODEL = 'BAAI/bge-large-en-v1.5'
    CONVERSATION_GAP_MINUTES = 30
    BATCH_SIZE = 256
    RECREATE_COLLECTION = True

    sms_db_to_qdrant(
        sms_db_path=SMS_DB_PATH,
        target_phone_number=HER_PHONE_NUMBER,
        qdrant_host=QDRANT_HOST,
        qdrant_port=QDRANT_PORT,
        qdrant_grpc_port=QDRANT_GRPC_PORT,
        sentence_transformer_model_name=SENTENCE_TRANSFORMER_MODEL,
        conversation_gap_minutes=CONVERSATION_GAP_MINUTES,
        batch_size=BATCH_SIZE,
        recreate_collection=RECREATE_COLLECTION,
    )
    print('\nmessage ingestion complete.')
