# 🔧 DrRepo Troubleshooting Guide

This guide helps you diagnose and fix common issues with DrRepo.

---

## Quick Diagnostics

Run this command to check your setup:

```
python scripts/diagnose.py
```


This will check:
- ✅ Python version
- ✅ Required dependencies
- ✅ API key configuration
- ✅ File permissions
- ✅ Network connectivity

---

## Common Issues

### 1. API Connection Failures

#### Symptom
```
APIConnectionError: GitHub API error
APIConnectionError: Connection refused
```


#### Root Causes
- Invalid or expired API tokens
- Network connectivity issues
- API service downtime
- Rate limiting

#### Solutions

**A. Check GitHub Token Validity**
Using GitHub CLI
```
gh auth status
```

Using Python
```
python -c "from github import Github; from src.utils.config import config; 
print(Github(config.github_token).get_user().login)"
```

**B. Verify `.env` Configuration**

Check if .env file exists
```
ls -la .env
```

Verify required keys are set
```
cat .env | grep -E "GROQ_API_KEY|GH_TOKEN|TAVILY_API_KEY"
```


**C. Test API Connectivity**
Test GitHub API
```
python -c "from src.tools.github_tool import GitHubTool; 
print(GitHubTool().execute('https://github.com/python/cpython'))"
```

Test Groq API
```
python -c "from langchain_groq import ChatGroq; f
rom src.utils.config import config; 
ChatGroq(api_key=config.groq_api_key).invoke('test')"
```

Test Tavily API
```
python -c "from tavily import TavilyClient; 
from src.utils.config import config; 
TavilyClient(config.tavily_api_key).search('test', max_results=1)"
```

**D. Check Rate Limits**
Check GitHub rate limit
```
curl -H "Authorization: token YOUR_GITHUB_TOKEN" https://api.github.com/rate_limit
```


Visit: https://github.com/settings/tokens to check token permissions

#### Prevention
- Use authenticated requests (included by default)
- Implement request caching
- Monitor rate limit usage
- Set up API key rotation

---

### 2. LLM Timeout Errors

#### Symptom
```
TimeoutError: Request timed out
Slow response times (>30 seconds)
```

#### Root Causes
- Groq API overload
- Large prompt size
- Network latency
- Model unavailability

#### Solutions

**A. Reduce Token Limits**

Edit `.env`:
```
MAX_TOKENS=1000 # Reduced from 2000
TIMEOUT=60 # Increased from 30
```

**B. Check Groq API Status**

Visit: https://status.groq.com

**C. Switch to OpenAI Provider**

Edit `.env`:
```
MODEL_PROVIDER=openai
OPENAI_API_KEY=sk-your-key-here
MODEL_NAME=gpt-3.5-turbo # or gpt-4
```

**D. Monitor Response Times**
Enable debug logging
```
LOG_LEVEL=DEBUG
```

Check logs for timing
```
tail -f logs/app.log | grep "latency"
```


#### Prevention
- Use smaller models for development
- Implement request timeout handling
- Cache LLM responses when possible
- Monitor Groq API status

---

### 3. FAISS/RAG Issues

#### Symptom
```
ModuleNotFoundError: No module named 'faiss'
ImportError: DLL load failed while importing _swigfaiss
```

#### Root Causes
- FAISS not installed
- Wrong FAISS version (CPU vs GPU)
- Missing system dependencies

#### Solutions

**A. Install FAISS CPU Version (Recommended)**
```
pip uninstall faiss-gpu faiss-cpu # Remove existing
pip install faiss-cpu
```


**B. Install FAISS GPU Version (If CUDA Available)**
Check CUDA availability
```
python -c "import torch; print(torch.cuda.is_available())"
```

Install GPU version
```
pip install faiss-gpu
```

**C. Test FAISS Installation**

```
python -c "import faiss; print(f'FAISS version: {faiss.version}')"
```


**D. Alternative: Use ChromaDB**

If FAISS continues to cause issues, switch to ChromaDB:

```
pip install chromadb
```

Update rag_retriever.py to use ChromaDB instead


#### Prevention
- Always use `faiss-cpu` unless you have GPU
- Pin FAISS version in requirements.txt
- Test after installation

---

### 4. Memory Issues

#### Symptom
```
MemoryError: Unable to allocate array
Killed (process terminated by OS)
```

#### Root Causes
- Large repository analysis
- High RAG chunk size
- Insufficient system RAM
- Memory leaks

#### Solutions

**A. Reduce RAG Chunk Size**

Edit `src/tools/rag_retriever.py`:
```
self.text_splitter = RecursiveCharacterTextSplitter(
chunk_size=500, # Reduced from 1000
chunk_overlap=100 # Reduced from 200
)
```

**B. Analyze Smaller Repositories**
Start with small repos
```
python -m src.main https://github.com/user/small-repo
```

**C. Increase Docker Memory Limit**

Edit `docker-compose.yml`:
```
services:
drrepo:
mem_limit: 4g # Increased from default
memswap_limit: 4g
```

**D. Monitor Memory Usage**

Linux/Mac
```
top -p $(pgrep -f "streamlit")
```

Windows
```
tasklist | findstr python
```


#### Prevention
- Start with small repositories
- Implement pagination for large repos
- Clear vector store after analysis
- Use streaming for large files

---

### 5. Import Errors

#### Symptom
```
ModuleNotFoundError: No module named 'src'
ImportError: cannot import name 'retry_with_backoff'
```


#### Root Causes
- Missing dependencies
- Incorrect Python path
- Virtual environment not activated

#### Solutions

**A. Reinstall Dependencies**
```
pip install -r requirements.txt --force-reinstall
```


**B. Check Python Path**
Verify you're in project root
```
pwd
```

Check if src directory exists
```
ls -la src/
```

Add to Python path
```
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

**C. Activate Virtual Environment**

Linux/Mac
```
source venv/bin/activate
```

Windows
```
venv\Scripts\activate
```

Verify activation
```
which python # Should point to venv
```


**D. Test Imports**
```
python -c "from src.utils.retry import retry_with_backoff; print('✓ Imports working')"
```


---

### 6. Streamlit Errors

#### Symptom
```
StreamlitAPIException: Session state error
Port 8501 already in use
```


#### Root Causes
- Multiple Streamlit instances
- Port conflicts
- Session state corruption

#### Solutions

**A. Kill Existing Streamlit Process**

Linux/Mac
```
pkill -f streamlit
```

Or find and kill specific process
```
lsof -ti:8501 | xargs kill -9
```

Windows
```
netstat -ano | findstr :8501
taskkill /PID <PID> /F
```

**B. Use Different Port**
```
streamlit run app.py --server.port=8502
```

**C. Clear Streamlit Cache**
```
rm -rf ~/.streamlit/
```

**D. Reset Session State**

Add to `app.py`:
```
if st.button("Reset Session"):
st.session_state.clear()
st.rerun()
```

---

### 7. Docker Issues

#### Symptom

```
docker: Error response from daemon
Container unhealthy
Build failed
```

#### Root Causes
- Insufficient Docker resources
- Port conflicts
- Image build errors
- Network issues

#### Solutions

**A. Clear Docker Cache**
```
docker system prune -a
docker volume prune
```

**B. Rebuild Without Cache**
```
docker-compose down
docker-compose build --no-cache
docker-compose up
```

**C. Check Container Logs**
```
docker logs drrepo --tail 100
docker logs drrepo -f # Follow
```

**D. Increase Docker Resources**

Docker Desktop → Settings → Resources:
- CPUs: 4+
- Memory: 8GB+
- Disk: 20GB+

**E. Test Health Check**
```
docker exec drrepo curl http://localhost:8501/_stcore/health
```

---

## Health Check Commands

### System Health
Full health check
```
python scripts/health_check.py
```

Quick validation
```
python -c "from src.utils.config import config; 
print('✓ Valid' if config.validate() else '✗ Invalid')"
```

Check individual components
```
python scripts/check_components.py
```

### API Connectivity

GitHub
```
python -c "from src.tools.github_tool import GitHubTool; 
GitHubTool().execute('https://github.com/python/cpython')['name']"
```

Groq
```
python -c "from langchain_groq import ChatGroq; 
from src.utils.config import config; 
ChatGroq(api_key=config.groq_api_key, model='llama-3.3-70b-versatile').invoke('ping')"
```

Tavily
```
python -c "from src.tools.web_search_tool import WebSearchTool; 
len(WebSearchTool().search_generic('test', max_results=1))"
```

### Dependency Check

List outdated packages
```
pip list --outdated
```

Check for security vulnerabilities
```
pip-audit
```

Verify all imports
```
python scripts/verify_imports.py
```

---

## Logs and Debugging

### Enable Debug Logging

Edit `.env`:
```
LOG_LEVEL=DEBUG
```

### View Logs

Tail application logs
```
tail -f logs/app.log
```

Search for errors
```
grep -i "error" logs/app.log
```

Filter by date
```
grep "2025-12-19" logs/app.log
```

### Log Locations

logs/
├── app.log # Main application log
├── error.log # Error-only log
├── streamlit.log # Streamlit-specific log
└── health.log # Health check log


### Common Log Patterns

Find rate limit errors
```
grep "rate limit" logs/app.log
```

Find failed API calls
```
grep "API.*failed" logs/app.log
```

Find agent errors
```
grep "Agent.*error" logs/app.log
```


---

## Maintenance Tasks

### Daily
- [ ] Monitor error logs for recurring issues
- [ ] Check application uptime
- [ ] Verify API connectivity

### Weekly
- [ ] Review `logs/app.log` for patterns
- [ ] Check API key expiration dates
- [ ] Update dependencies: `pip list --outdated`
- [ ] Test health endpoints

### Monthly
- [ ] Rotate API keys for security
- [ ] Review and update documentation
- [ ] Analyze performance metrics
- [ ] Update best practices queries
- [ ] Run full test suite: `pytest tests/ -v`

### Quarterly
- [ ] Review and update dependencies
- [ ] Security audit: `pip-audit`
- [ ] Performance benchmarking
- [ ] User feedback review

---

## Performance Optimization

### Slow Analysis

Profile execution time
```
python -m cProfile -o profile.stats -m src.main <repo_url>
python -c "import pstats;
p = pstats.Stats('profile.stats'); 
p.sort_stats('cumulative').print_stats(20)"
```
Identify bottlenecks

Look for functions taking >5 seconds


### Memory Optimization

Monitor memory during analysis
```
python scripts/memory_profiler.py <repo_url>
```

Optimize RAG chunk size

Edit src/tools/rag_retriever.py


### Cache Responses
Add caching to expensive operations
```
from functools import lru_cache

@lru_cache(maxsize=100)
def expensive_function(arg):
# ...
```


---

## Getting Help

### Self-Service
1. **Check logs**: `tail -f logs/app.log`
2. **Enable debug mode**: `LOG_LEVEL=DEBUG` in `.env`
3. **Run diagnostics**: `python scripts/diagnose.py`
4. **Search existing issues**: https://github.com/ak-rahul/DrRepo/issues

### Community Support
1. **GitHub Discussions**: https://github.com/ak-rahul/DrRepo/discussions
2. **Report bug**: https://github.com/ak-rahul/DrRepo/issues/new?template=bug_report.md
3. **Request feature**: https://github.com/ak-rahul/DrRepo/issues/new?template=feature_request.md

---

## FAQ

**Q: Why is analysis so slow?**
A: Large repositories or high API latency. Try analyzing smaller repos first or check network connection.

**Q: Can I use DrRepo offline?**
A: No, DrRepo requires internet for API calls (GitHub, LLM, search).

**Q: How do I update DrRepo?**
A: `git pull origin main && pip install -r requirements.txt --upgrade`

**Q: Is my API key secure?**
A: Yes, keys are stored in `.env` (not committed to git). Never share your `.env` file.

**Q: Can I analyze private repositories?**
A: Yes, ensure your GitHub token has `repo` scope for private repo access.

**Q: How much does it cost to run?**
A: Groq is free (with limits), GitHub token is free, Tavily has free tier. Costs vary with usage.

---

**Last Updated**: December 19, 2025  
**DrRepo Version**: 1.0.0

For more help, visit: https://github.com/ak-rahul/DrRepo

