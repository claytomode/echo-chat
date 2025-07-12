import os


API_KEY = os.getenv('OPENAI_API_KEY')

BASE_URL = os.getenv('OPENAI_BASE_URL')

MODEL_NAME = os.getenv('MODEL_NAME', 'gemini-2.5-flash')

QDRANT_URL = os.getenv('QDRANT_URL')
QDRANT_HTTP_PORT = 6333
QDRANT_GRPC_PORT = 6334
QDRANT_API_KEY = None

QDRANT_COLLECTION_NAME = os.getenv('QDRANT_COLLECTION_NAME', 'echo_chat')
USE_CUDA = bool(int(os.getenv('USE_CUDA', '0')))

SENTENCE_TRANSFORMER_MODEL_NAME = 'BAAI/bge-large-en-v1.5'
SPARSE_MODEL_NAME = 'prithivida/Splade_PP_en_v1'
