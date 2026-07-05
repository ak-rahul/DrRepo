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
python -c "from github import Github; from src.config import Config;
c = Config.from_env(); print(Github(c.github_token).get_user().login)"
```

**B. Verify `.env` Configuration**

Check if .env file exists
```
ls -la .env
```

Verify required keys are set
```
cat .env | grep -E "GROQ_API_KEY|GH_TOKEN"
```


**C. Test API Connectivity**
Test GitHub API
```
python -c "from src.collectors.github_metadata import collect_github_metadata; \
from src.config import Config; \
print(collect_github_metadata('https://github.com/python/cpython', Config.from_env()))"
```

Test Groq API
```
python -c "from langchain_groq import ChatGroq; from src.config import Config; \
c = Config.from_env(); ChatGroq(api_key=c.groq_api_key, model=c.model_name).invoke('test')"
```

Test OSV.dev connectivity (used by the dependency audit collector)
```
python -c "import httpx; print(httpx.get('https://api.osv.dev/v1/query', timeout=5).status_code)"
```

Test deps.dev connectivity (used by license compatibility checking)
```
python -c "import httpx; print(httpx.get('https://api.deps.dev/v3/systems/pypi/packages/requests/versions/2.6.0', timeout=5).status_code)"
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

**A. Reduce Token Limits, or Give Deep Investigations More Room**

Edit `.env`:
```
MAX_TOKENS=1000                       # Reduced from the default 2000
INVESTIGATOR_TIMEOUT_SECONDS=180      # Increased from the default 90, for slow models
MAX_TOOL_CALLS_PER_INVESTIGATOR=4     # Reduced from the default 8, if deep investigations time out
```

If it's specifically a deep (agentic) investigation timing out or looping, see
[Deep Investigation Issues](#8-deep-investigation-agentic-issues) below rather than tuning
tokens/timeouts blindly.

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

### 3. Static Analysis Tool Issues (ruff / semgrep / bandit)

#### Symptom
```
collector_status.static_analysis.tool_status.semgrep == "skipped: semgrep not installed"
FileNotFoundError: [Errno 2] No such file or directory: 'git'
```

#### Root Causes
- `ruff`/`semgrep`/`bandit` not installed (they ship as regular `requirements.txt` entries, so
  this usually means a stale/incomplete `pip install`)
- `git` not on PATH (required at runtime -- the clone collector shells out to it)

#### Solutions

**A. Verify the tools are installed and on PATH**
```
pip install -r requirements.txt
python -c "import shutil; print([shutil.which(t) for t in ('git', 'ruff', 'semgrep', 'bandit')])"
```

**B. Disable a collector instead of failing the whole analysis**

Each collector degrades gracefully already, but you can turn one off explicitly in `.env`:
```
ENABLE_SEMGREP=false
ENABLE_BANDIT=false
```

**C. Check `collector_status` in the report**

Every report includes a `collector_status` field showing exactly which collectors ran, were
skipped, or errored, and why -- check that first before assuming a tool is broken.

#### Prevention
- Run `python scripts/check_components.py` after any environment change; it reports which
  external tools are found on PATH.
- Pin tool versions in `requirements.txt` (already done) so a `pip install` upgrade can't
  silently change behavior.

---

### 4. Memory Issues

#### Symptom
```
MemoryError: Unable to allocate array
Killed (process terminated by OS)
```

#### Root Causes
- Very large repository clone
- Insufficient system RAM
- Memory leaks

#### Solutions

**A. Lower the Clone Size Limit**

Edit `.env`:
```
CLONE_MAX_SIZE_MB=150   # Reduced from the default 300
```
Repositories over this size are skipped (not crashed on) -- see `collector_status.repo_clone`.

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

### 8. Deep Investigation (Agentic) Issues

#### Symptom
```
Investigation stopped after reaching its tool-call budget before concluding.
Deep investigation failed: <error>
```

#### Root Causes
- The Lead Investigator (`src/agents/planner.py`) sent a category "deep," and its investigator
  (`src/agents/investigator.py`) hit its step budget (`GraphRecursionError`) before it finished
  reasoning, or the underlying LLM call raised an exception mid-investigation.
- Both cases are caught and degrade to a neutral fallback result (score 50, no issues, a
  message saying so) rather than failing the whole report -- so this shows up as a suspiciously
  neutral score for one category, not a crash.

#### Solutions

**A. Give it more tool calls**

Edit `.env`:
```
MAX_TOOL_CALLS_PER_INVESTIGATOR=12   # Increased from the default 8
```
Each tool call costs roughly 2 steps of the internal recursion budget, so this is the first
thing to raise if a category keeps hitting its budget.

**B. Check `investigation_depth` and `investigation_trace` in the report**

Every category score carries `investigation_depth` (`"shallow"` or `"deep"`) and, for deep
categories, an `investigation_trace` listing the exact tool calls made. If the trace is short or
empty despite a "deep" verdict, that's this fallback path, not a genuine clean bill of health.

**C. Fall back to the deterministic shallow pipeline**

Edit `.env`:
```
ENABLE_DEEP_INVESTIGATION=false
```
This forces every category through the fast, single-LLM-call shallow path (the planner isn't
even invoked) -- useful to isolate whether an issue is in the agentic layer specifically, and as
a cheaper/faster mode in general.

#### Prevention
- Keep `MAX_TOOL_CALLS_PER_INVESTIGATOR` proportional to repository size/complexity.
- Watch `logs/app.log` for `Investigator for <category> hit its step limit` /
  `Investigator for <category> failed` warnings -- both are logged before the fallback kicks in.

---

## Health Check Commands

### System Health
Full health check
```
python scripts/health_check.py
```

Quick validation
```
python -c "from src.config import Config; \
c = Config.from_env(); missing = c.validate_for_llm(); \
print('Valid' if not missing else f'Missing: {missing}')"
```

Check individual components
```
python scripts/check_components.py
```

### API Connectivity

GitHub
```
python -c "from src.collectors.github_metadata import collect_github_metadata; \
from src.config import Config; \
print(collect_github_metadata('https://github.com/python/cpython', Config.from_env()).data.get('name'))"
```

Groq
```
python -c "from langchain_groq import ChatGroq; from src.config import Config; \
c = Config.from_env(); ChatGroq(api_key=c.groq_api_key, model=c.model_name).invoke('ping')"
```

OSV.dev (used by the dependency audit collector)
```
python -c "import httpx; print(httpx.get('https://api.osv.dev/v1/query', timeout=5).status_code)"
```

deps.dev (used by license compatibility checking)
```
python -c "import httpx; print(httpx.get('https://api.deps.dev/v3/systems/pypi/packages/requests/versions/2.6.0', timeout=5).status_code)"
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

`src/utils/logger.py`'s `setup_logger()` writes everything -- app, Streamlit, and health-check
logging alike, since they all import the same `logger` -- to a single file:

```
logs/
└── app.log   # Every component logs here; there is no separate error/streamlit/health log
```


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

Lower the clone size limit (see [Memory Issues](#4-memory-issues) above) or disable a
collector/feature toggle in `.env` to reduce what gets pulled into memory per run.


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
A: Not currently -- DrRepo only supports public repositories (the clone collector rejects
anything other than a plain `https://github.com/<owner>/<repo>` URL, and never embeds
credentials in the clone URL). This is a deliberate scope boundary, not a bug.

**Q: Why does one category's score look suspiciously neutral (around 50) with a vague summary?**
A: That's the deep-investigation fallback path, not a real verdict -- see
[Deep Investigation Issues](#8-deep-investigation-agentic-issues).

**Q: How much does it cost to run?**
A: Groq is free (with limits), a GitHub token is free, and OSV.dev's API is free and
unauthenticated. Costs vary only with Groq usage if you exceed the free tier.

---

**DrRepo Version**: 2.0.0

For more help, visit: https://github.com/ak-rahul/DrRepo

