import os

API_KEY = os.getenv("OPENAI_API_KEY")

BASE_URL = os.getenv("OPENAI_BASE_URL")

MODEL_NAME = os.getenv("MODEL_NAME")

QDRANT_URL = os.getenv("QDRANT_URL")

QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "my_collection")