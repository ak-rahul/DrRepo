"""RAG retriever for code context extraction."""
from typing import List, Dict, Optional
import os
from pathlib import Path
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from src.tools.base_tool import BaseTool
from src.utils.config import config

class RAGRetriever(BaseTool):
    """Tool for retrieving relevant code context using RAG."""
    
    def __init__(self):
        super().__init__("RAGRetriever")
        self.embeddings = OpenAIEmbeddings(api_key=config.openai_api_key)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )
        self.vector_store = None
    
    def execute(self, readme_content: str, query: str, top_k: int = 3) -> List[Dict]:
        """
        Execute RAG retrieval on README content.
        
        Args:
            readme_content: README text to index
            query: Query to search for
            top_k: Number of results to return
            
        Returns:
            List of relevant chunks
        """
        try:
            # Create vector store from README
            self._create_vector_store(readme_content)
            
            # Perform similarity search
            results = self.vector_store.similarity_search_with_score(query, k=top_k)
            
            # Format results
            formatted_results = [
                {
                    "content": doc.page_content,
                    "score": float(score),
                    "metadata": doc.metadata
                }
                for doc, score in results
            ]
            
            self.logger.info(f"Retrieved {len(formatted_results)} relevant chunks")
            return formatted_results
            
        except Exception as e:
            return [self._handle_error(e)]
    
    def _create_vector_store(self, content: str):
        """Create FAISS vector store from content."""
        # Split content into chunks
        chunks = self.text_splitter.split_text(content)
        
        # Create documents
        documents = [
            Document(page_content=chunk, metadata={"chunk_id": i})
            for i, chunk in enumerate(chunks)
        ]
        
        # Create vector store
        self.vector_store = FAISS.from_documents(documents, self.embeddings)
    
    def search_for_claims(self, readme_content: str, claims: List[str]) -> Dict:
        """
        Search README for evidence of specific claims.
        
        Args:
            readme_content: README content
            claims: List of claims to verify
            
        Returns:
            Dictionary mapping claims to evidence
        """
        results = {}
        
        for claim in claims:
            matches = self.execute(readme_content, claim, top_k=2)
            results[claim] = {
                "found": len(matches) > 0 and matches[0].get("score", 1.0) < 0.5,
                "evidence": matches[0].get("content", "") if matches else ""
            }
        
        return results
