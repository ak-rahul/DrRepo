"""Base class for all agents in DrRepo."""

from abc import ABC, abstractmethod
from typing import Dict
import os

from langchain_core.messages import SystemMessage, HumanMessage

from src.utils.config import config
from src.utils.logger import logger
from src.utils.retry import retry_with_backoff


class BaseAgent(ABC):
    """Abstract base class for all DrRepo agents.
    
    Provides standardized LLM interaction with dual provider support (Groq/OpenAI),
    logging integration, and consistent error handling patterns.
    
    Architecture Design:
        - Each agent inherits this base to ensure consistent interface
        - Temperature can be customized per agent for task-specific creativity
        - LLM provider selection handled automatically from config
    
    Attributes:
        name (str): Agent identifier for logging and state tracking
        system_prompt (str): Agent-specific system instructions for LLM
        llm: Language model instance (ChatGroq or ChatOpenAI)
        logger: Shared logging instance
    
    Supported LLM Providers:
        - Groq (default): Free, fast inference with llama-3.3-70b-versatile
        - OpenAI: Fallback option with GPT models
    """

    def __init__(self, name: str, system_prompt: str, temperature: float = 0.3):
        """Initialize base agent with LLM configuration.

        Args:
            name: Agent name for identification in logs and state
            system_prompt: System-level instructions defining agent behavior
            temperature: LLM temperature (0.0-1.0) controlling response creativity
                - 0.0-0.2: Factual, deterministic (data extraction)
                - 0.3-0.4: Balanced (recommendations)
                - 0.5+: Creative (brainstorming)
        """
        self.name = name
        self.system_prompt = system_prompt
        self.logger = logger

        # Initialize LLM based on provider configuration
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
            state: Current workflow state dictionary containing:
                - repo_url: GitHub repository URL
                - repo_data: Repository metadata (populated by RepoAnalyzer)
                - Previous agent outputs in dedicated state keys

        Returns:
            Updated state dictionary with agent's analysis results
        """
        pass

    @retry_with_backoff(
        max_retries=3,
        backoff_factor=2.0,
        initial_delay=2.0,
        max_delay=30.0,
        exceptions=(Exception,)
    )
    def _call_llm(self, user_prompt: str) -> str:
        """Call LLM with system and user prompts with automatic retry.

        Args:
            user_prompt: User prompt string with analysis request

        Returns:
            LLM response content as string

        Raises:
            Exception: If LLM call fails after all retries (API error, timeout, etc.)
            
        Retry Strategy:
            - Max 3 retries with exponential backoff
            - Initial delay: 2s, then 4s, then 8s
            - Retries on any exception (rate limits, timeouts, API errors)
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
        """Log agent execution with agent-specific prefix.

        Args:
            message: Log message describing current execution step
        """
        self.logger.info(f"[{self.name}] {message}")
