# ⚙️ Configuration Guide

## Environment Variables

### Required Variables

#### GROQ_API_KEY
**Free LLM API**

Get your key: [https://console.groq.com](https://console.groq.com)

GROQ_API_KEY=gsk_your_groq_api_key_here


**Features:**
- Free tier available
- Fast inference (llama-3.3-70b)
- No credit card required
- Generous rate limits

---

#### GITHUB_TOKEN
**GitHub API access**

Get your token: [https://github.com/settings/tokens](https://github.com/settings/tokens)

GITHUB_TOKEN=ghp_your_github_token_here


**Required Permissions:**
- `public_repo` (for public repositories)
- `repo` (for private repositories, optional)

**Note:** Without token, rate limit is 60 requests/hour. With token: 5000 requests/hour.

---

#### TAVILY_API_KEY
**Web search API**

Get your key: [https://app.tavily.com](https://app.tavily.com)

TAVILY_API_KEY=tvly_your_tavily_api_key_here


**Features:**
- Free tier: 1000 searches/month
- Used for finding similar repositories
- README best practices research

---

### Optional Variables

#### Model Configuration

LLM Provider (groq or openai)
MODEL_PROVIDER=groq

Model name
MODEL_NAME=llama-3.3-70b-versatile

Temperature (0.0-1.0)
TEMPERATURE=0.3

Max tokens per request
MAX_TOKENS=2000


**Available Models:**

**Groq (Recommended - Free):**
- `llama-3.3-70b-versatile` (default, best)
- `llama-3.1-70b-versatile`
- `mixtral-8x7b-32768`

**OpenAI (Paid):**
- `gpt-4-turbo-preview`
- `gpt-4`
- `gpt-3.5-turbo`

---

#### Application Settings

Logging level (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL=INFO

Maximum retries for API calls
MAX_RETRIES=3

Request timeout (seconds)
TIMEOUT=30


---

#### LangSmith Tracing (Optional)

For debugging and monitoring:

LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_api_key
LANGCHAIN_PROJECT=drrepo


Get key: [https://smith.langchain.com](https://smith.langchain.com)

---

## Configuration File

### .env File Structure

Create `.env` in project root:

==================================
DrRepo Configuration
==================================
===== Required APIs =====
Groq LLM (Free)
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx

GitHub API
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

Tavily Search
TAVILY_API_KEY=tvly_xxxxxxxxxxxxxxxxxxxx

===== Model Configuration =====
MODEL_PROVIDER=groq
MODEL_NAME=llama-3.3-70b-versatile
TEMPERATURE=0.3
MAX_TOKENS=2000

===== Application Settings =====
LOG_LEVEL=INFO
MAX_RETRIES=3
TIMEOUT=30

===== Optional: LangSmith Tracing =====
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=drrepo


---

## Python Configuration

### Config Class

from src.utils.config import config

Access configuration
print(config.groq_api_key)
print(config.model_name)
print(config.temperature)

Validate configuration
if config.validate():
print("✓ Configuration valid")
else:
print("✗ Missing required API keys")


---

## Customization

### Agent Temperature

Control randomness in agent responses:

In src/agents/repo_analyzer.py
def init(self):
super().init(
name="RepoAnalyzer",
system_prompt="...",
temperature=0.2 # Lower = more deterministic
)


**Temperature Guide:**
- `0.0-0.2`: Very deterministic, factual
- `0.3-0.5`: Balanced (default)
- `0.6-0.8`: More creative
- `0.9-1.0`: Very creative, less consistent

---

### System Prompts

Customize agent behavior by editing system prompts:

In src/agents/content_improver.py
system_prompt = """You are a technical writing expert.

Your role is to:

Improve README structure

Suggest missing sections

Enhance clarity

Focus on: [YOUR CUSTOM FOCUS]
"""


---

### Quality Score Weights

Adjust quality score calculation:

In src/tools/markdown_tool.py
def _calculate_quality_score(self, analysis):
score = 0

# Customize weights
if analysis["word_count"] >= 1000:
    score += 25  # Was 20

# Add custom criteria
if analysis["has_contributing"]:
    score += 5

return score



---

## Docker Configuration

### Environment File for Docker

Create `.env.docker`:

GROQ_API_KEY=gsk_your_key
GITHUB_TOKEN=ghp_your_token
TAVILY_API_KEY=tvly_your_key
MODEL_PROVIDER=groq
MODEL_NAME=llama-3.3-70b-versatile



### Docker Compose

docker-compose.yml
services:
drrepo:
env_file:
- .env.docker
environment:
- LOG_LEVEL=INFO



---

## Production Configuration

### Recommended Settings

Production .env
GROQ_API_KEY=gsk_prod_key_here
GITHUB_TOKEN=ghp_prod_token_here
TAVILY_API_KEY=tvly_prod_key_here

MODEL_PROVIDER=groq
MODEL_NAME=llama-3.3-70b-versatile
TEMPERATURE=0.3
MAX_TOKENS=2000

LOG_LEVEL=WARNING
MAX_RETRIES=5
TIMEOUT=60

Enable tracing
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_PROJECT=drrepo-production


---

## Security Best Practices

### 1. Never Commit .env

Add to `.gitignore`:

.env
.env.*
!.env.example


### 2. Use Separate Keys

- Development keys in `.env`
- Production keys in `.env.production`
- CI/CD keys in GitHub Secrets

### 3. Rotate Keys Regularly

- GitHub tokens: Every 90 days
- API keys: Every 6 months
- Monitor usage for anomalies

### 4. Minimal Permissions

GitHub token permissions:
- ✅ `public_repo` (if analyzing public repos only)
- ❌ Don't grant `repo` unless needed
- ❌ Don't grant `admin` permissions

---

## Troubleshooting

### "Config validation failed"

**Check:**
1. `.env` file exists in project root
2. All required keys present
3. No typos in key names
4. No extra spaces around `=`

### "Invalid API key"

**Solutions:**
- Regenerate key from provider
- Check key not expired
- Verify correct provider (groq vs openai)

### "Rate limit exceeded"

**Solutions:**
- Increase `TIMEOUT` value
- Add `MAX_RETRIES=5`
- Wait and retry
- Check API quotas on provider dashboard

---

## Advanced Configuration

### Custom LLM Provider

In src/agents/base_agent.py
if model_provider == 'anthropic':
from langchain_anthropic import ChatAnthropic
self.llm = ChatAnthropic(
model="claude-3-opus-20240229",
api_key=config.anthropic_api_key
)


### Multiple Model Support

Use different models for different agents
class RepoAnalyzerAgent(BaseAgent):
def init(self):
super().init(
name="RepoAnalyzer",
system_prompt="...",
temperature=0.2
)
# Override with faster model
self.llm = ChatGroq(
model="llama-3.1-8b-instant",
api_key=config.groq_api_key
)


---

## Configuration Checklist

- [ ] Created `.env` file
- [ ] Added all required API keys
- [ ] Verified keys work (test with simple request)
- [ ] Set appropriate temperature
- [ ] Configured logging level
- [ ] Added `.env` to `.gitignore`
- [ ] Created `.env.example` for team
- [ ] Documented custom configurations
- [ ] Tested in development
- [ ] Separate production config ready
