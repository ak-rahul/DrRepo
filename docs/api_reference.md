# 📚 API Reference

Complete API documentation for DrRepo.

***

## Main Application

### PublicationAssistant

Main application class for DrRepo.

```python
from src.main import PublicationAssistant

assistant = PublicationAssistant()
```

**Methods** 

1.  Analyze a GitHub repository.
```
analyze(repo_url: str, description: str = "") -> dict
```

Analyze a GitHub repository.

Parameters:

- repo_url (str): GitHub repository URL

- description (str, optional): Repository description for context

Returns:

- dict: Analysis results containing:

- repository: Repository metadata

- summary: Overall assessment

- action_items: Priority recommendations

- metadata: Metadata suggestions

- content: Content improvements

- quality_review: Quality assessment

- fact_check: Verification results

Example:

```
assistant = PublicationAssistant()
result = assistant.analyze(
    "https://github.com/psf/requests",
    "Popular Python HTTP library"
)

print(f"Quality Score: {result['repository']['current_score']}")
print(f"Status: {result['summary']['status']}")
```

2. Analyze repository and save report to file.

```
analyze_and_save(repo_url: str, description: str = "") -> str
```
Parameters:

- repo_url (str): GitHub repository URL

- description (str, optional): Repository description

Returns:

- str: Path to saved report file

Example:

```
report_path = assistant.analyze_and_save(
    "https://github.com/django/django"
)
print(f"Report saved to: {report_path}")

```