# 🏗️ DrRepo Architecture

## System Overview

DrRepo is a multi-agent AI system built using **LangGraph** for orchestrating specialized agents that analyze GitHub repositories and provide actionable recommendations.

## Architecture Diagram

┌─────────────────────────────────────────────────────────────┐
│ DrRepo System │
├─────────────────────────────────────────────────────────────┤
│ │
│ ┌────────────────┐ ┌──────────────────┐ │
│ │ Streamlit UI │────────▶│ Main Controller │ │
│ └────────────────┘ └──────────────────┘ │
│ │ │
│ ▼ │
│ ┌───────────────────┐ │
│ │ LangGraph │ │
│ │ Workflow │ │
│ └───────────────────┘ │
│ │ │
│ ┌────────────────────┼────────────────────┐ │
│ │ │ │ │
│ ▼ ▼ ▼ │
│ ┌────────────────┐ ┌────────────────┐ ┌──────────┐ │
│ │ Repo Analyzer │ │ Metadata │ │ Content │ │
│ │ Agent │ │ Recommender │ │ Improver │ │
│ └────────────────┘ └────────────────┘ └──────────┘ │
│ │ │ │ │
│ ▼ ▼ ▼ │
│ ┌────────────────┐ ┌────────────────┐ │
│ │ Reviewer │ │ Fact Checker │ │
│ │ Critic │ │ (RAG) │ │
│ └────────────────┘ └────────────────┘ │
│ │ │ │
│ └────────────────────┼─────────────────────┐ │
│ ▼ │ │
│ ┌────────────────┐ │ │
│ │ Synthesizer │ │ │
│ └────────────────┘ │ │
│ │ │ │
│ ▼ │ │
│ ┌────────────────┐ │ │
│ │ Final Report │ │ │
│ └────────────────┘ │ │
└─────────────────────────────────────────────────────────────┘


## Core Components

### 1. **Frontend Layer**
- **Streamlit Web Interface** (`app.py`)
  - User input for repository URL
  - Real-time progress tracking
  - Interactive results display
  - JSON report download

### 2. **Application Layer**
- **Main Controller** (`src/main.py`)
  - Entry point for CLI and API
  - Report generation
  - Error handling
  - Configuration validation

### 3. **Orchestration Layer**
- **LangGraph Workflow** (`src/graph/workflow.py`)
  - Sequential agent execution
  - State management
  - Result synthesis
  - Error propagation

- **State Manager** (`src/graph/state.py`)
  - Typed state schema
  - Message accumulation
  - Data flow between agents

### 4. **Agent Layer**

#### 🔍 RepoAnalyzer Agent
**Purpose:** Fetches and analyzes repository data

**Inputs:**
- Repository URL

**Outputs:**
- Repository metadata (stars, forks, language)
- README content and structure
- File organization analysis
- Initial quality assessment

**Tools Used:**
- GitHubTool
- MarkdownTool

---

#### 🏷️ MetadataRecommender Agent
**Purpose:** Optimizes repository discoverability

**Inputs:**
- Repository metadata
- README content

**Outputs:**
- Improved title/description suggestions
- Relevant topic recommendations
- SEO keyword optimization
- Similar successful repositories

**Tools Used:**
- WebSearchTool (Tavily)

---

#### ✍️ ContentImprover Agent
**Purpose:** Enhances README documentation

**Inputs:**
- README content
- Structure analysis
- Best practices from web

**Outputs:**
- Missing section identification
- Content improvement suggestions
- Visual element recommendations
- Code example suggestions

**Tools Used:**
- WebSearchTool
- MarkdownTool

---

#### ✅ ReviewerCritic Agent
**Purpose:** Performs quality assessment

**Inputs:**
- All previous analyses
- Repository structure
- Documentation completeness

**Outputs:**
- Quality score breakdown
- Critical issue identification
- Priority recommendations
- Overall status assessment

**Tools Used:**
- None (LLM-based analysis)

---

#### 🔎 FactChecker Agent
**Purpose:** Verifies README claims

**Inputs:**
- README content
- Repository data

**Outputs:**
- Claim verification results
- Inconsistency identification
- Evidence-based validation

**Tools Used:**
- RAGRetriever (FAISS + HuggingFace embeddings)

### 5. **Tool Layer**

#### GitHubTool
- **API:** PyGithub
- **Functions:**
  - Fetch repository metadata
  - Get README content
  - Analyze file structure
  - Check for CI/CD, tests, docs

#### RAGRetriever
- **Vector DB:** FAISS (CPU)
- **Embeddings:** HuggingFace (`all-MiniLM-L6-v2`)
- **Functions:**
  - Index README content
  - Semantic search
  - Claim verification

#### WebSearchTool
- **API:** Tavily Search
- **Functions:**
  - Find similar repositories
  - Get README best practices
  - Research industry standards

#### MarkdownTool
- **Functions:**
  - Parse markdown structure
  - Count sections, images, code blocks
  - Calculate quality score
  - Identify missing sections

### 6. **LLM Layer**
- **Primary:** Groq (llama-3.3-70b-versatile)
- **Alternative:** OpenAI GPT-4
- **Configuration:** Environment-based selection

## Data Flow

User Input (Repository URL)
↓

GitHub API Fetch (Repository Data + README)
↓

Sequential Agent Processing:

RepoAnalyzer → Initial analysis

MetadataRecommender → Discoverability

ContentImprover → Documentation quality

ReviewerCritic → Quality assessment

FactChecker → Claim verification (RAG)
↓

Result Synthesis (Priority ranking)
↓

Final Report (JSON + UI Display)


## State Management

**State Schema:**
{
"repo_url": str,
"description": str,
"repo_data": Dict,
"code_structure": Dict,
"analysis": List[Dict],
"metadata_recommendations": List[Dict],
"content_improvements": List[Dict],
"quality_review": List[Dict],
"fact_check_results": List[Dict],
"messages": List,
"current_agent": str,
"errors": List[str]
}


## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Orchestration** | LangGraph | Agent workflow management |
| **LLM** | Groq (Llama 3.3 70B) | AI reasoning |
| **Framework** | LangChain | LLM integration |
| **Vector DB** | FAISS | Semantic search |
| **Embeddings** | HuggingFace | Text vectorization |
| **APIs** | GitHub API, Tavily | Data sources |
| **Frontend** | Streamlit | Web interface |
| **Testing** | pytest | Unit & integration tests |
| **CI/CD** | GitHub Actions | Automation |

## Design Patterns

### 1. **Agent Pattern**
Each agent is a specialized expert with:
- Clear responsibility
- Defined inputs/outputs
- Independent operation
- Error handling

### 2. **Pipeline Pattern**
Sequential processing:

Agent1 → Agent2 → Agent3 → Agent4 → Agent5 → Synthesis


### 3. **RAG Pattern**
For fact-checking:

Query → Embedding → Vector Search → Retrieve Context → LLM Verification


### 4. **Factory Pattern**
LLM initialization based on config:

if provider == "groq":
llm = ChatGroq(...)
else:
llm = ChatOpenAI(...)


## Scalability Considerations

### Current Design
- Sequential agent execution
- Single repository analysis
- Local FAISS index per request

### Future Enhancements
- Parallel agent execution for independent tasks
- Batch repository processing
- Persistent vector store
- Caching layer for repeated analyses
- Async API endpoints

## Security

- API keys stored in environment variables
- No sensitive data logging
- GitHub token with minimal permissions
- Rate limiting on external APIs
- Input validation for URLs

## Performance

**Typical Analysis Time:** 30-60 seconds

**Breakdown:**
- GitHub API fetch: 2-5s
- LLM calls (5 agents): 20-40s
- Web search: 3-8s
- RAG indexing: 2-5s
- Synthesis: 1-2s

## Error Handling

- Try-catch blocks in each agent
- Error accumulation in state
- Graceful degradation
- Detailed logging
- User-friendly error messages
