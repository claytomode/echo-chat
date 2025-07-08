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
            msg["conversation_id"] = f"conv_{current_conversation_id}"
            processed_messages.append(msg)
            continue

        prev_msg = processed_messages[i - 1]

        time_diff_seconds = msg["timestamp_raw"] - prev_msg["timestamp_raw"]
        time_diff_minutes = time_diff_seconds / 60

        if time_diff_minutes > time_gap_threshold_minutes:
            current_conversation_id += 1

        msg["conversation_id"] = f"conv_{current_conversation_id}"
        processed_messages.append(msg)

    return processed_messages


def sms_db_to_qdrant(
    sms_db_path: str,
    target_phone_number: str,
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
    qdrant_grpc_port: int = 6334,
    collection_name: str = "echo_chat",
): ...
