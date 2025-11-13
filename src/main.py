"""Main application entry point for DrRepo."""
import sys
import json
from pathlib import Path
from datetime import datetime
from src.graph.workflow import PublicationAssistantWorkflow
from src.utils.config import config
from src.utils.logger import logger


class PublicationAssistant:
    """Main application class for DrRepo."""
    
    def __init__(self):
        """Initialize publication assistant."""
        self.logger = logger
        
        # Validate configuration
        if not config.validate():
            raise ValueError("Missing required API keys. Check your .env file.")
        
        # Initialize workflow
        self.workflow = PublicationAssistantWorkflow()
        
        # Ensure reports directory exists
        self.reports_dir = Path("reports")
        self.reports_dir.mkdir(exist_ok=True)
    
    def analyze(self, repo_url: str, description: str = "") -> dict:
        """Analyze a repository.
        
        Args:
            repo_url: GitHub repository URL
            description: Optional repository description
        
        Returns:
            Analysis results dictionary with final_summary
        """
        try:
            # Execute workflow
            result = self.workflow.execute(repo_url, description)
            
            # Extract final_summary from state
            final_summary = result.get("final_summary", {})
            
            # If final_summary doesn't exist, create minimal structure from state
            if not final_summary or not final_summary.get("repository"):
                self.logger.warning("final_summary incomplete, building from state")
                
                repo_data = result.get("repo_data", {})
                code_structure = result.get("code_structure", {})
                quality_score = code_structure.get("quality_score", 0)
                
                # Determine status
                if quality_score >= 80:
                    status = "Excellent"
                elif quality_score >= 60:
                    status = "Good"
                elif quality_score >= 40:
                    status = "Needs Improvement"
                else:
                    status = "Poor"
                
                # Build minimal action items
                action_items = []
                missing_sections = code_structure.get("missing_sections", [])
                
                for section in missing_sections[:5]:
                    action_items.append({
                        "priority": "High",
                        "category": "Documentation",
                        "action": f"Add {section} section to README",
                        "impact": "Critical for completeness"
                    })
                
                # Create complete structure
                final_summary = {
                    "repository": {
                        "name": repo_data.get("name", "Unknown"),
                        "url": repo_data.get("url", repo_url),
                        "current_score": quality_score,
                        "language": repo_data.get("language", "Unknown"),
                        "stars": repo_data.get("stars", 0)
                    },
                    "summary": {
                        "status": status,
                        "total_suggestions": len(action_items),
                        "critical_issues": len([s for s in missing_sections if s.lower() in ['installation', 'usage', 'license']])
                    },
                    "action_items": action_items,
                    "metadata": {
                        "word_count": code_structure.get("word_count", 0),
                        "section_count": code_structure.get("section_count", 0),
                        "code_examples": code_structure.get("code_block_count", 0)
                    },
                    "content": {
                        "missing_sections": missing_sections,
                        "quality_score": quality_score
                    },
                    "quality_review": {},
                    "fact_check": {}
                }
            
            return final_summary
            
        except Exception as e:
            self.logger.error(f"Analysis failed: {str(e)}")
            raise
    
    def analyze_and_save(self, repo_url: str, description: str = "") -> str:
        """Analyze repository and save report to file.
        
        Args:
            repo_url: GitHub repository URL
            description: Optional repository description
        
        Returns:
            Path to saved report file
        """
        # Run analysis
        recommendations = self.analyze(repo_url, description)
        
        # Generate report filename
        repo_name = recommendations.get("repository", {}).get("name", "repository")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{repo_name}_{timestamp}_report.json"
        filepath = self.reports_dir / filename
        
        # Save report
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(recommendations, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"Report exported to: {filepath}")
        return str(filepath)
    
    def print_summary(self, recommendations: dict):
        """Print analysis summary to console.
        
        Args:
            recommendations: Analysis results dictionary
        """
        repo = recommendations.get("repository", {})
        summary = recommendations.get("summary", {})
        
        print("\n" + "="*80)
        print("📊 DRREPO - ANALYSIS REPORT")
        print("="*80 + "\n")
        
        print(f"🔗 Repository: {repo.get('name', 'Unknown')}")
        print(f"   URL: {repo.get('url', 'N/A')}")
        print(f"   Current Quality Score: {repo.get('current_score', 0):.1f}/100\n")
        
        print(f"📈 Overall Status: {summary.get('status', 'Unknown')}")
        print(f"   Total Suggestions: {summary.get('total_suggestions', 0)}")
        print(f"   Critical Issues: {summary.get('critical_issues', 0)}\n")
        
        print("🎯 TOP PRIORITY ACTION ITEMS:\n")
        action_items = recommendations.get("action_items", [])
        
        if action_items:
            for i, item in enumerate(action_items[:3], 1):
                print(f"{i}. [{item.get('priority', 'N/A')}] {item.get('action', 'N/A')}")
                print(f"   → {item.get('impact', 'N/A')}\n")
        else:
            print("   No action items generated.\n")
        
        print("="*80)
        print("💾 Full report available in JSON format")
        print("="*80 + "\n")


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m src.main <repo_url> [description]")
        print("Example: python -m src.main https://github.com/psf/requests 'Python HTTP library'")
        sys.exit(1)
    
    repo_url = sys.argv[1]
    description = sys.argv[2] if len(sys.argv) > 2 else ""
    
    try:
        print(f"\n🚀 Analyzing {repo_url}...\n")
        
        assistant = PublicationAssistant()
        
        logger.info(f"Analyzing repository: {repo_url}")
        recommendations = assistant.analyze(repo_url, description)
        
        logger.info("Analysis complete")
        
        # Print summary
        assistant.print_summary(recommendations)
        
        # Save report
        report_path = assistant.analyze_and_save(repo_url, description)
        print(f"✅ Analysis complete! Full report saved to: {report_path}")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Analysis cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        print(f"\n❌ Error: {str(e)}")
        print("Check logs for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
