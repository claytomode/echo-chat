from data_processing.create_qdrant_db import upload_knowledge_base_to_qdrant
import dotenv
import os

dotenv.load_dotenv()
os.environ['USE_CUDA'] = '1'
upload_knowledge_base_to_qdrant(
    knowledge_base_db_path='knowledge_base.db',
    recreate_collection=True,
)
