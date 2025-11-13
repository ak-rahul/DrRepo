# 📚 API Reference

## Main Application

### PublicationAssistant

Main application class for DrRepo.

from src.main import PublicationAssistant

assistant = PublicationAssistant()

#### Methods

##### `analyze(repo_url: str, description: str = "") -> dict`

Analyze a GitHub repository.

**Parameters:**
- `repo_url` (str): GitHub repository URL
- `description` (str, optional): Repository description for context

**Returns:**
- `dict`: Analysis results containing:
  - `repository`: Repository metadata
  - `summary`: Overall assessment
  - `action_items`: Priority recommendations
  - `metadata`: Metadata suggestions
  - `content`: Content improvements
  - `quality_review`: Quality assessment
  - `fact_check`: Verification results

**Example:**
assistant = PublicationAssistant()
result = assistant.analyze(
"https://github.com/psf/requests",
"Popular Python HTTP library"
)

print(f"Quality Score: {result['repository']['current_score']}")
print(f"Status: {result['summary']['status']}")


---

##### `analyze_and_save(repo_url: str, description: str = "") -> str`

Analyze repository and save report to file.

**Parameters:**
- `repo_url` (str): GitHub repository URL
- `description` (str, optional): Repository description

**Returns:**
- `str`: Path to saved report file

**Example:**

report_path = assistant.analyze_and_save(
"https://github.com/django/django"
)
print(f"Report saved to: {report_path}")


---

## Workflow

### PublicationAssistantWorkflow

LangGraph workflow orchestrating all agents.

from src.graph.workflow import PublicationAssistantWorkflow

workflow = PublicationAssistantWorkflow()


#### Methods

##### `execute(repo_url: str, description: str = "") -> Dict`

Execute complete workflow.

**Parameters:**
- `repo_url` (str): GitHub repository URL
- `description` (str, optional): Repository description

**Returns:**
- `Dict`: Complete workflow state with all agent results

**Example:**
workflow = PublicationAssistantWorkflow()
result = workflow.execute("https://github.com/fastapi/fastapi")

Access final summary
summary = result["final_summary"]


---

## Agents

All agents inherit from `BaseAgent` and implement the `execute(state: Dict) -> Dict` method.

### BaseAgent

Abstract base class for all agents.

from src.agents.base_agent import BaseAgent

class CustomAgent(BaseAgent):
def init(self):
super().init(
name="CustomAgent",
system_prompt="You are a custom agent...",
temperature=0.3
)

def execute(self, state: Dict) -> Dict:
    # Agent logic here
    return state



---

### RepoAnalyzerAgent

from src.agents.repo_analyzer import RepoAnalyzerAgent

agent = RepoAnalyzerAgent()
result = agent.execute(state)


**State Input:**
- `repo_url`: Repository URL

**State Output:**
- `repo_data`: Repository metadata
- `code_structure`: README analysis
- `analysis`: Analysis results

---

### MetadataRecommenderAgent

from src.agents.metadata_recommender import MetadataRecommenderAgent

agent = MetadataRecommenderAgent()
result = agent.execute(state)


**State Input:**
- `repo_data`: Repository metadata

**State Output:**
- `metadata_recommendations`: Metadata suggestions

---

### ContentImproverAgent

from src.agents.content_improver import ContentImproverAgent

agent = ContentImproverAgent()
result = agent.execute(state)


**State Input:**
- `repo_data`: Repository metadata
- `code_structure`: README analysis

**State Output:**
- `content_improvements`: Content suggestions

---

### ReviewerCriticAgent

from src.agents.reviewer_critic import ReviewerCriticAgent

agent = ReviewerCriticAgent()
result = agent.execute(state)


**State Input:**
- All previous analyses

**State Output:**
- `quality_review`: Quality assessment

---

### FactCheckerAgent

from src.agents.fact_checker import FactCheckerAgent

agent = FactCheckerAgent()
result = agent.execute(state)
**State Input:**
- `repo_data`: Repository with README

**State Output:**
- `fact_check_results`: Verification results

---

## Tools

### GitHubTool

from src.tools.github_tool import GitHubTool

tool = GitHubTool()
repo_data = tool.execute("https://github.com/user/repo")


**Returns:**

{
"name": str,
"full_name": str,
"description": str,
"url": str,
"stars": int,
"forks": int,
"language": str,
"topics": List[str],
"license": str,
"readme_content": str,
"file_structure": Dict
}


---

### RAGRetriever

from src.tools.rag_retriever import RAGRetriever

retriever = RAGRetriever()

Index documents
retriever.index_documents(["document 1", "document 2"])

Search
results = retriever.search("query text", k=3)


**Methods:**
- `index_documents(documents: List[str])`: Index documents
- `search(query: str, k: int = 3)`: Search for similar documents
- `search_for_claims(readme: str, claims: List[str])`: Verify claims

---

### WebSearchTool

from src.tools.web_search_tool import WebSearchTool

tool = WebSearchTool()

Search similar repositories
repos = tool.search_similar_repositories("Python", "web framework")

Get README best practices
practices = tool.get_readme_best_practices()


---

### MarkdownTool

from src.tools.markdown_tool import MarkdownTool

tool = MarkdownTool()
analysis = tool.execute(readme_content)


**Returns:**
{
"word_count": int,
"section_count": int,
"code_block_count": int,
"image_count": int,
"link_count": int,
"badge_count": int,
"missing_sections": List[str],
"has_table_of_contents": bool,
"quality_score": float
}


---

## Configuration

### Config

from src.utils.config import config

Access configuration
api_key = config.groq_api_key
model = config.model_name
temp = config.temperature

Validate configuration
is_valid = config.validate()


**Attributes:**
- `groq_api_key`: Groq API key
- `github_token`: GitHub token
- `tavily_api_key`: Tavily API key
- `model_provider`: "groq" or "openai"
- `model_name`: LLM model name
- `temperature`: LLM temperature
- `max_tokens`: Max tokens per request

---

## CLI Usage

Analyze repository
python -m src.main https://github.com/user/repo "Description"

Or use make
make cli


---

## Streamlit App

Run web interface
streamlit run app.py

Or use make
make run


---

## Response Format

### Analysis Result

{
"repository": {
"name": "repo-name",
"url": "https://github.com/user/repo",
"current_score": 75.5
},
"summary": {
"status": "Good",
"total_suggestions": 12,
"critical_issues": 2
},
"action_items": [
{
"priority": "High",
"category": "Documentation",
"action": "Add installation section",
"impact": "Critical for usability"
}
],
"metadata": {
"suggestions": ["..."],
"similar_repos": [...]
},
"content": {
"missing_sections": ["Installation", "Contributing"],
"improvements": ["..."],
"quality_score": 75.5
},
"quality_review": {
"checklist": {
"has_readme": true,
"has_tests": true,
"has_ci": false
},
"feedback": ["..."]
},
"fact_check": {
"verified": 3,
"results": ["..."]
}
}