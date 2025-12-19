"""Diagnostic script for DrRepo troubleshooting."""

import sys
import os
import subprocess
from importlib import import_module

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def print_header(title):
    """Print formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def check_python_version():
    """Check Python version."""
    print_header("Python Version")
    version = sys.version_info
    print(f"Python {version.major}.{version.minor}.{version.micro}")
    
    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print("❌ FAIL: Python 3.9+ required")
        return False
    else:
        print("✅ PASS: Python version OK")
        return True


def check_dependencies():
    """Check if required packages are installed."""
    print_header("Dependencies")
    
    required = [
        'streamlit',
        'langchain',
        'langchain_groq',
        'github',
        'tavily',
        'faiss',
        'sentence_transformers',
        'python-dotenv'
    ]
    
    all_installed = True
    for package in required:
        try:
            # Handle special cases
            if package == 'faiss':
                import_module('faiss')
                print(f"✅ {package}")
            elif package == 'sentence_transformers':
                import_module('sentence_transformers')
                print(f"✅ {package}")
            elif package == 'python-dotenv':
                import_module('dotenv')
                print(f"✅ {package}")
            else:
                import_module(package)
                print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} - NOT INSTALLED")
            all_installed = False
    
    return all_installed


def check_environment():
    """Check environment variables."""
    print_header("Environment Configuration")
    
    from src.utils.config import config
    
    checks = {
        "GROQ_API_KEY": bool(config.groq_api_key),
        "GH_TOKEN": bool(config.github_token),
        "TAVILY_API_KEY": bool(config.tavily_api_key)
    }
    
    all_set = True
    for key, value in checks.items():
        if value:
            print(f"✅ {key}: Set")
        else:
            print(f"❌ {key}: NOT SET")
            all_set = False
    
    return all_set


def check_imports():
    """Check if DrRepo modules can be imported."""
    print_header("DrRepo Modules")
    
    modules = [
        'src.utils.config',
        'src.utils.logger',
        'src.utils.retry',
        'src.utils.health_check',
        'src.utils.exceptions',
        'src.tools.github_tool',
        'src.tools.web_search_tool',
        'src.tools.rag_retriever',
        'src.agents.base_agent',
        'src.main'
    ]
    
    all_imported = True
    for module in modules:
        try:
            import_module(module)
            print(f"✅ {module}")
        except Exception as e:
            print(f"❌ {module} - {str(e)[:50]}")
            all_imported = False
    
    return all_imported


def check_api_connectivity():
    """Check API connectivity."""
    print_header("API Connectivity")
    
    # GitHub API
    try:
        from src.utils.config import config
        from github import Github
        
        gh = Github(config.github_token, timeout=5)
        user = gh.get_user()
        _ = user.login
        print(f"✅ GitHub API: Connected (user: {user.login})")
        github_ok = True
    except Exception as e:
        print(f"❌ GitHub API: {str(e)[:50]}")
        github_ok = False
    
    # Groq API
    try:
        from langchain_groq import ChatGroq
        from src.utils.config import config
        
        llm = ChatGroq(api_key=config.groq_api_key, model='llama-3.3-70b-versatile', timeout=5)
        llm.invoke("ping")
        print("✅ Groq API: Connected")
        groq_ok = True
    except Exception as e:
        print(f"❌ Groq API: {str(e)[:50]}")
        groq_ok = False
    
    # Tavily API
    try:
        from tavily import TavilyClient
        from src.utils.config import config
        
        client = TavilyClient(api_key=config.tavily_api_key)
        client.search(query="test", max_results=1)
        print("✅ Tavily API: Connected")
        tavily_ok = True
    except Exception as e:
        print(f"❌ Tavily API: {str(e)[:50]}")
        tavily_ok = False
    
    return github_ok and groq_ok and tavily_ok


def check_file_permissions():
    """Check file and directory permissions."""
    print_header("File Permissions")
    
    directories = ['logs', 'reports', 'data']
    all_ok = True
    
    for directory in directories:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
                print(f"✅ {directory}/: Created")
            except Exception as e:
                print(f"❌ {directory}/: Cannot create - {str(e)}")
                all_ok = False
        else:
            if os.access(directory, os.W_OK):
                print(f"✅ {directory}/: Writable")
            else:
                print(f"❌ {directory}/: NOT writable")
                all_ok = False
    
    return all_ok


def main():
    """Run all diagnostic checks."""
    print("\n🔧 DrRepo Diagnostic Tool")
    print("=" * 60)
    
    results = {}
    
    results['python'] = check_python_version()
    results['dependencies'] = check_dependencies()
    results['environment'] = check_environment()
    results['imports'] = check_imports()
    results['api'] = check_api_connectivity()
    results['permissions'] = check_file_permissions()
    
    # Summary
    print_header("Diagnostic Summary")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"\nPassed: {passed}/{total}")
    print(f"Failed: {total - passed}/{total}")
    
    if all(results.values()):
        print("\n✅ All checks passed! DrRepo should work correctly.")
        return 0
    else:
        print("\n❌ Some checks failed. Please fix the issues above.")
        print("\nFor help, see: docs/TROUBLESHOOTING.md")
        return 1


if __name__ == "__main__":
    sys.exit(main())
