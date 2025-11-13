"""Base class for all agents in DrRepo."""
from abc import ABC, abstractmethod
from typing import Dict
import os
from langchain_core.messages import SystemMessage, HumanMessage
from src.utils.config import config
from src.utils.logger import logger


class BaseAgent(ABC):
    """Abstract base class for all agents.
    
    Supports both Groq and OpenAI LLM providers.
    """
    
    def __init__(self, name: str, system_prompt: str, temperature: float = 0.3):
        """Initialize base agent.
        
        Args:
            name: Agent name
            system_prompt: System prompt for LLM
            temperature: LLM temperature (0.0-1.0)
        """
        self.name = name
        self.system_prompt = system_prompt
        self.logger = logger
        
        # Initialize LLM based on provider
        model_provider = config.model_provider
        
        if model_provider == 'groq':
            from langchain_groq import ChatGroq
            self.llm = ChatGroq(
                model=config.model_name,
                temperature=temperature,
                api_key=config.groq_api_key
            )
        else:
            from langchain_openai import ChatOpenAI
            self.llm = ChatOpenAI(
                model=config.model_name,
                temperature=temperature,
                max_tokens=config.max_tokens,
                api_key=config.openai_api_key
            )
    
    @abstractmethod
    def execute(self, state: Dict) -> Dict:
        """Execute agent's main task.
        
        Args:
            state: Current workflow state
        
        Returns:
            Updated state dictionary
        """
        pass
    
    def _call_llm(self, user_prompt: str) -> str:
        """Call LLM with system and user prompts.
        
        Args:
            user_prompt: User prompt string
        
        Returns:
            LLM response content
        
        Raises:
            Exception: If LLM call fails
        """
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
        """Log agent execution.
        
        Args:
            message: Log message
        """
        self.logger.info(f"[{self.name}] {message}")
