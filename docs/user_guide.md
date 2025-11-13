# 📖 User Guide

## Getting Started

### Installation

#### Prerequisites
- Python 3.9 or higher
- pip package manager
- Git

#### Steps

1. **Clone the repository:**
git clone https://github.com/yourusername/DrRepo.git
cd DrRepo


2. **Create virtual environment:**
python -m venv venv

Activate (Windows)
venv\Scripts\activate

Activate (Linux/Mac)
source venv/bin/activate


3. **Install dependencies:**
pip install -r requirements.txt
4. **Set up API keys:**

Create a `.env` file in the project root:
Groq API (Free - get from https://console.groq.com)
GROQ_API_KEY=your_groq_api_key_here

GitHub Token (get from https://github.com/settings/tokens)
GITHUB_TOKEN=your_github_token_here

Tavily API (get from https://app.tavily.com)
TAVILY_API_KEY=your_tavily_api_key_here

Model Configuration
MODEL_PROVIDER=groq
MODEL_NAME=llama-3.3-70b-versatile


---

## Usage

### Web Interface (Recommended)

1. **Start Streamlit app:**


streamlit run app.py


2. **Open browser:**
   - Automatically opens at `http://localhost:8501`
   - If not, manually navigate to the URL shown in terminal

3. **Analyze a repository:**
   - Enter GitHub repository URL
   - (Optional) Add description for better analysis
   - Click "🚀 Analyze"
   - Wait 30-60 seconds
   - View results and download JSON report

---

### Command Line Interface

Basic usage
python -m src.main https://github.com/psf/requests

With description
python -m src.main https://github.com/django/django "Python web framework"


**Output:**
- Console summary
- JSON report saved to `reports/` directory

---

### Python API

from src.main import PublicationAssistant

Initialize
assistant = PublicationAssistant()

Analyze repository
result = assistant.analyze(
repo_url="https://github.com/fastapi/fastapi",
description="Modern Python web framework"
)

Access results
print(f"Quality Score: {result['repository']['current_score']:.1f}/100")
print(f"Status: {result['summary']['status']}")

Print action items
for item in result['action_items'][:3]:
print(f"[{item['priority']}] {item['action']}")

Save report
report_path = assistant.analyze_and_save(repo_url, description)


---

## Understanding Results

### Quality Score (0-100)

| Score | Status | Meaning |
|-------|--------|---------|
| 80-100 | Excellent | Professional, complete documentation |
| 60-79 | Good | Solid documentation, minor improvements needed |
| 40-59 | Needs Improvement | Significant gaps, needs work |
| 0-39 | Poor | Critical issues, major overhaul needed |

**Score Calculation:**
- Word count (20 points)
- Section structure (20 points)
- Code examples (15 points)
- Visual elements (10 points)
- Missing sections penalty (-30 points max)
- Extras (TOC, badges, links): +20 points

---

### Action Items

**Priority Levels:**
- 🔴 **High**: Critical for basic usability (Installation, Usage, License)
- 🟡 **Medium**: Important for quality (Examples, Screenshots, Contributing)
- 🟢 **Low**: Nice to have (Badges, Advanced docs, Changelog)

**Example:**
🔴 High - Add Installation section
→ Impact: Critical for usability
→ Category: Documentation

🟡 Medium - Include code examples
→ Impact: Improves understanding
→ Category: Content


---

### Report Sections

#### 1. **Repository Overview**
- Name, URL, language
- Stars, forks, watchers
- Topics and description
- Quality score

#### 2. **Metadata Recommendations**
- Improved title/description
- Relevant topics to add
- SEO keywords
- Similar successful repositories

#### 3. **Content Improvements**
- Missing sections identified
- README enhancement suggestions
- Visual element recommendations
- Code example suggestions

#### 4. **Quality Review**
- Completeness checklist
- Professional standards assessment
- Gap analysis
- Score breakdown

#### 5. **Fact Check**
- Claims verified
- Inconsistencies found
- Evidence-based validation

---

## Best Practices

### Getting Better Results

1. **Provide Context:**
   - Add description when analyzing
   - Helps AI understand project purpose

2. **Analyze Complete Repositories:**
   - Works best with existing READMEs
   - More data = better recommendations

3. **Regular Analysis:**
   - Re-analyze after updates
   - Track improvement over time

---

## Common Use Cases

### 1. New Project Setup
**Goal:** Start with professional documentation

**Steps:**
1. Create basic README
2. Run DrRepo analysis
3. Implement top priority actions
4. Add missing sections
5. Re-analyze to verify

---

### 2. Documentation Improvement
**Goal:** Enhance existing README

**Steps:**
1. Run initial analysis
2. Review action items
3. Add missing content
4. Improve structure
5. Verify improvements

---

### 3. Pre-Publication Check
**Goal:** Ensure professional quality before release

**Steps:**
1. Complete all development
2. Run DrRepo analysis
3. Fix critical issues (Installation, Usage, License)
4. Address high-priority items
5. Aim for 70+ score

---

### 4. Competitive Analysis
**Goal:** Compare with similar projects

**Steps:**
1. Analyze your repository
2. Note similar repositories suggested
3. Analyze competitors
4. Compare scores and features
5. Implement best practices

---

## Troubleshooting

### Common Issues

#### "Missing API keys"
**Solution:**
- Check `.env` file exists
- Verify all required keys present
- Ensure no extra spaces
- Restart application

#### "Invalid GitHub URL"
**Solution:**
- Use full URL: `https://github.com/user/repo`
- Check repository is public
- Verify GitHub token permissions

#### "Analysis taking too long"
**Solution:**
- Normal time: 30-60 seconds
- Large repositories may take longer
- Check internet connection
- Verify API rate limits not exceeded

#### "Quality score seems low"
**Solution:**
- Review missing sections
- Add code examples
- Increase word count (aim for 500+)
- Add visual elements

---

## Tips & Tricks

### Maximize Quality Score

1. **Essential Sections** (Must have):
   - Installation instructions
   - Usage examples
   - Features list
   - License information

2. **Code Examples** (15 points):
   - Add at least 2-3 code blocks
   - Show real usage
   - Include different scenarios

3. **Visual Elements** (10 points):
   - Screenshots of UI/output
   - Architecture diagrams
   - Badges for build status, version, etc.

4. **Structure** (20 points):
   - Use clear headers (##, ###)
   - Add table of contents for long READMEs
   - Organize logically

5. **Extras** (+20 points):
   - Badges (build, coverage, version)
   - Links to documentation
   - Contributing guidelines

---

## Keyboard Shortcuts (Web UI)

| Action | Shortcut |
|--------|----------|
| Focus URL input | `Ctrl + /` |
| Submit analysis | `Ctrl + Enter` |
| Download report | `Ctrl + S` |

---

## FAQ

**Q: How long does analysis take?**
A: Typically 30-60 seconds per repository.

**Q: Can I analyze private repositories?**
A: Yes, if your GitHub token has access.

**Q: Is my data stored?**
A: Reports saved locally in `reports/` directory. No cloud storage.

**Q: Can I analyze multiple repositories?**
A: Yes, but one at a time via UI. Use Python API for batch processing.

**Q: What languages are supported?**
A: All languages on GitHub. Focus is on documentation, not code.

**Q: How accurate is the fact-checking?**
A: Uses RAG for verification. Generally reliable, but review results.

**Q: Can I customize agents?**
A: Yes, modify agent prompts in `src/agents/` files.

---

## Next Steps

- Read [Configuration Guide](configuration.md)
- Check [API Reference](api_reference.md)
- Review [Architecture](architecture.md)
- Contribute on GitHub
