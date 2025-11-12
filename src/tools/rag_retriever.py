"""RAG-based retriever for fact checking."""
from typing import List, Dict
import os
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from src.utils.config import config
from src.utils.logger import logger


class RAGRetriever:
    """RAG retriever for document-based fact checking."""
    
    def __init__(self):
        self.logger = logger
        # Use free HuggingFace embeddings instead of OpenAI
        self.embeddings = HuggingFaceEmbeddings(
            model_name='sentence-transformers/all-MiniLM-L6-v2'
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )
        self.vector_store = None
    
    def index_documents(self, documents: List[str]) -> None:
        """Index documents for retrieval."""
        try:
            splits = self.text_splitter.create_documents(documents)
            self.vector_store = FAISS.from_documents(splits, self.embeddings)
            self.logger.info(f"Indexed {len(splits)} document chunks")
        except Exception as e:
            self.logger.error(f"Error indexing documents: {str(e)}")
            raise
    
    def search(self, query: str, k: int = 3) -> List[Dict]:
        """Search for relevant documents."""
        if not self.vector_store:
            self.logger.warning("No documents indexed")
            return []
        
        try:
            results = self.vector_store.similarity_search(query, k=k)
            return [
                {"content": doc.page_content, "metadata": doc.metadata}
                for doc in results
            ]
        except Exception as e:
            self.logger.error(f"Error searching: {str(e)}")
            return []
    
    def search_for_claims(
        self,
        readme_content: str,
        claims: List[str]
    ) -> List[Dict]:
        """Search for evidence supporting or refuting claims."""
        # Index the README
        self.index_documents([readme_content])
        
        results = []
        for claim in claims:
            matches = self.search(claim, k=2)
            results.append({
                "claim": claim,
                "evidence": matches,
                "verified": len(matches) > 0
            })
        
        return results
