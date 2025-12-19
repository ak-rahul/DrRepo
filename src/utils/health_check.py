"""Health check utilities for monitoring system components."""

import time
from typing import Dict, Tuple
from datetime import datetime

from src.utils.config import config
from src.utils.logger import logger


class HealthChecker:
    """Centralized health checking for all system components."""

    @staticmethod
    def check_groq() -> Tuple[bool, Dict]:
        """Check Groq API health.
        
        Returns:
            Tuple of (is_healthy: bool, details: dict)
        """
        if config.model_provider != 'groq':
            return True, {"status": "not_used", "message": "Using different provider"}
        
        try:
            start_time = time.time()
            
            from langchain_groq import ChatGroq
            llm = ChatGroq(
                model=config.model_name,
                api_key=config.groq_api_key,
                timeout=5
            )
            
            # Quick ping test
            llm.invoke("ping")
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            logger.info("Groq API health check: OK")
            return True, {
                "status": "up",
                "latency_ms": latency_ms,
                "model": config.model_name
            }
            
        except Exception as e:
            logger.error(f"Groq API health check failed: {str(e)}")
            return False, {
                "status": "down",
                "error": str(e)[:100],  # Truncate long errors
                "error_type": type(e).__name__
            }

    @staticmethod
    def check_openai() -> Tuple[bool, Dict]:
        """Check OpenAI API health.
        
        Returns:
            Tuple of (is_healthy: bool, details: dict)
        """
        if config.model_provider != 'openai':
            return True, {"status": "not_used", "message": "Using different provider"}
        
        try:
            start_time = time.time()
            
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=config.model_name,
                api_key=config.openai_api_key,
                timeout=5
            )
            
            # Quick ping test
            llm.invoke("ping")
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            logger.info("OpenAI API health check: OK")
            return True, {
                "status": "up",
                "latency_ms": latency_ms,
                "model": config.model_name
            }
            
        except Exception as e:
            logger.error(f"OpenAI API health check failed: {str(e)}")
            return False, {
                "status": "down",
                "error": str(e)[:100],
                "error_type": type(e).__name__
            }

    @staticmethod
    def check_github() -> Tuple[bool, Dict]:
        """Check GitHub API health.
        
        Returns:
            Tuple of (is_healthy: bool, details: dict)
        """
        try:
            start_time = time.time()
            
            from github import Github
            github = Github(config.github_token, timeout=5)
            
            # FIXED: Get rate limit with correct attribute access
            rate_limit = github.get_rate_limit()
            
            # Access core rate limit correctly
            # PyGithub returns different structures depending on version
            try:
                # Try newer PyGithub version (>= 2.0)
                core_remaining = rate_limit.core.remaining
                core_limit = rate_limit.core.limit
            except AttributeError:
                # Fallback for older PyGithub versions
                try:
                    core_remaining = rate_limit.rate.remaining
                    core_limit = rate_limit.rate.limit
                except AttributeError:
                    # If both fail, try alternative method
                    rate_info = github.rate_limiting
                    core_remaining = rate_info[0]
                    core_limit = rate_info[1]
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Warn if rate limit is low
            is_healthy = core_remaining > 10
            
            logger.info(f"GitHub API health check: OK (remaining: {core_remaining})")
            return is_healthy, {
                "status": "up" if is_healthy else "degraded",
                "latency_ms": latency_ms,
                "rate_limit_remaining": core_remaining,
                "rate_limit_total": core_limit,
                "warning": "Low rate limit" if core_remaining < 100 else None
            }
            
        except Exception as e:
            logger.error(f"GitHub API health check failed: {str(e)}")
            return False, {
                "status": "down",
                "error": str(e)[:100],
                "error_type": type(e).__name__
            }

    @staticmethod
    def check_tavily() -> Tuple[bool, Dict]:
        """Check Tavily API health.
        
        Returns:
            Tuple of (is_healthy: bool, details: dict)
        """
        try:
            start_time = time.time()
            
            from tavily import TavilyClient
            client = TavilyClient(api_key=config.tavily_api_key)
            
            # Quick search test
            client.search(query="test", max_results=1, search_depth="basic")
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            logger.info("Tavily API health check: OK")
            return True, {
                "status": "up",
                "latency_ms": latency_ms
            }
            
        except Exception as e:
            logger.error(f"Tavily API health check failed: {str(e)}")
            return False, {
                "status": "down",
                "error": str(e)[:100],
                "error_type": type(e).__name__
            }

    @staticmethod
    def check_rag() -> Tuple[bool, Dict]:
        """Check RAG retriever (FAISS + HuggingFace) health.
        
        Returns:
            Tuple of (is_healthy: bool, details: dict)
        """
        try:
            start_time = time.time()
            
            from src.tools.rag_retriever import RAGRetriever
            retriever = RAGRetriever()
            
            # Quick test: index and search
            test_docs = ["This is a test document for health checking."]
            retriever.index_documents(test_docs)
            results = retriever.search("test", k=1)
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            logger.info("RAG retriever health check: OK")
            return True, {
                "status": "up",
                "latency_ms": latency_ms,
                "embeddings_model": "sentence-transformers/all-MiniLM-L6-v2"
            }
            
        except Exception as e:
            logger.error(f"RAG retriever health check failed: {str(e)}")
            return False, {
                "status": "down",
                "error": str(e)[:100],
                "error_type": type(e).__name__
            }

    @staticmethod
    def check_all() -> Dict:
        """Run all health checks and return comprehensive status.
        
        Returns:
            Dictionary with overall status and individual component details
        """
        components = {}
        all_healthy = True
        
        # Check LLM provider (Groq or OpenAI)
        if config.model_provider == 'groq':
            is_healthy, details = HealthChecker.check_groq()
            components["llm_groq"] = details
            all_healthy = all_healthy and is_healthy
        else:
            is_healthy, details = HealthChecker.check_openai()
            components["llm_openai"] = details
            all_healthy = all_healthy and is_healthy
        
        # Check GitHub API
        is_healthy, details = HealthChecker.check_github()
        components["github_api"] = details
        all_healthy = all_healthy and is_healthy
        
        # Check Tavily API
        is_healthy, details = HealthChecker.check_tavily()
        components["tavily_api"] = details
        all_healthy = all_healthy and is_healthy
        
        # Check RAG retriever
        is_healthy, details = HealthChecker.check_rag()
        components["rag_retriever"] = details
        all_healthy = all_healthy and is_healthy
        
        return {
            "status": "healthy" if all_healthy else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
            "provider": config.model_provider,
            "components": components
        }
