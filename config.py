import os
import dotenv

dotenv.load_dotenv()

API_KEY = os.getenv('OPENAI_API_KEY')

BASE_URL = os.getenv('OPENAI_BASE_URL')

MODEL_NAME = os.getenv('MODEL_NAME', 'gemini-2.5-flash')

QDRANT_URL = os.getenv('QDRANT_URL')

QDRANT_API_KEY = os.getenv('QDRANT_API_KEY')

QDRANT_COLLECTION_NAME = os.getenv('QDRANT_COLLECTION_NAME', 'echo_chat')
USE_CUDA = os.getenv('USE_CUDA', 'false')

SENTENCE_TRANSFORMER_MODEL_NAME = 'BAAI/bge-large-en-v1.5'
SPARSE_MODEL_NAME = 'prithivida/Splade_PP_en_v1'