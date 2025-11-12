"""Base class for all agents."""
from abc import ABC, abstractmethod
from typing import Dict
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from src.utils.config import config
from src.utils.logger import logger


class BaseAgent(ABC):
    """Abstract base class for agents."""
    
    def __init__(self, name: str, system_prompt: str, temperature: float = 0.3):
        self.name = name
        self.system_prompt = system_prompt
        self.logger = logger
        
        # Check which provider to use
        model_provider = os.getenv('MODEL_PROVIDER', 'openai')
        
        if model_provider == 'groq':
            from langchain_groq import ChatGroq
            self.llm = ChatGroq(
                model=os.getenv('MODEL_NAME', 'llama-3.1-70b-versatile'),
                temperature=temperature,
                api_key=os.getenv('GROQ_API_KEY')
            )
        else:
            # Default to OpenAI
            self.llm = ChatOpenAI(
                model=config.model_name,
                temperature=temperature,
                max_tokens=config.max_tokens,
                api_key=config.openai_api_key
            )
    
    @abstractmethod
    def execute(self, state: Dict) -> Dict:
        """Execute agent's main task."""
        pass
    
    def _call_llm(self, user_prompt: str) -> str:
        """Call LLM with system and user prompts."""
        try:
            response = self.llm.invoke([
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=user_prompt)
            ])
            return response.content
        except Exception as e:
            self.logger.error(f"LLM call failed in {self.name}: {str(e)}")
            raise
    
    def _log_execution(self, message: str):
        """Log agent execution."""
        self.logger.info(f"[{self.name}] {message}")
