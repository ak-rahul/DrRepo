"""Main application entry point."""
import json
import sys
from pathlib import Path
from typing import Optional
from src.graph.workflow import PublicationAssistantWorkflow
from src.utils.config import config
from src.utils.logger import setup_logger
from src.utils.validators import validate_github_url, ValidationError

logger = setup_logger("main", log_level=config.log_level, log_file="app.log")

class PublicationAssistant:
    """Main application class for Publication Assistant."""
    
    def __init__(self):
        """Initialize the publication assistant."""
        if not config.validate():
            raise ValueError(
                "Missing required API keys. Please check your .env file."
            )
        
        self.workflow = PublicationAssistantWorkflow()
        logger.info("Publication Assistant initialized")
    
    def analyze(
        self,
        repo_url: str,
        user_description: str = ""
    ) -> dict:
        """
        Analyze a GitHub repository and get recommendations.
        
        Args:
            repo_url: GitHub repository URL
            user_description: Optional brief project description
            
        Returns:
            Dictionary containing all recommendations
            
        Raises:
            ValidationError: If repo URL is invalid
        """
        # Validate input
        try:
            validate_github_url(repo_url)
        except ValidationError as e:
            logger.error(f"Invalid repository URL: {e}")
            raise
        
        logger.info(f"Analyzing repository: {repo_url}")
        
        # Run workflow
        recommendations = self.workflow.run(repo_url, user_description)
        
        logger.info("Analysis complete")
        return recommendations
    
    def export_report(
        self,
        recommendations: dict,
        output_file: str = "recommendations.json"
    ):
        """
        Export recommendations to JSON file.
        
        Args:
            recommendations: Recommendations dictionary
            output_file: Output filename
        """
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(recommendations, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Report exported to: {output_path}")
    
    def print_summary(self, recommendations: dict):
        """
        Print a formatted summary of recommendations.
        
        Args:
            recommendations: Recommendations dictionary
        """
        print("\n" + "="*80)
        print("📊 PUBLICATION ASSISTANT - ANALYSIS REPORT")
        print("="*80 + "\n")
        
        # Repository info
        repo = recommendations["repository"]
        print(f"🔗 Repository: {repo['name']}")
        print(f"   URL: {repo['url']}")
        print(f"   Current Quality Score: {repo['current_score']:.1f}/100\n")
        
        # Summary
        summary = recommendations["summary"]
        print(f"📈 Overall Status: {summary['status']}")
        print(f"   Total Suggestions: {summary['total_suggestions']}")
        print(f"   Critical Issues: {summary['critical_issues']}\n")
        
        # Action items
        print("🎯 TOP PRIORITY ACTION ITEMS:\n")
        for i, item in enumerate(recommendations["action_items"][:5], 1):
            print(f"{i}. [{item['priority']}] {item['action']}")
            print(f"   → {item['impact']}\n")
        
        print("="*80)
        print(f"💾 Full report available in JSON format")
        print("="*80 + "\n")

def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m src.main <github_repo_url> [description]")
        print("\nExample:")
        print("  python -m src.main https://github.com/user/repo 'My awesome project'")
        sys.exit(1)
    
    repo_url = sys.argv[1]
    user_description = sys.argv[2] if len(sys.argv) > 2 else ""
    
    try:
        # Initialize assistant
        assistant = PublicationAssistant()
        
        # Analyze repository
        print(f"\n🚀 Analyzing {repo_url}...\n")
        recommendations = assistant.analyze(repo_url, user_description)
        
        # Print summary
        assistant.print_summary(recommendations)
        
        # Export full report
        output_file = f"reports/{repo_url.split('/')[-1]}_report.json"
        assistant.export_report(recommendations, output_file)
        
        print(f"✅ Analysis complete! Full report saved to: {output_file}\n")
        
    except ValidationError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"❌ An unexpected error occurred. Check logs for details.")
        sys.exit(1)

if __name__ == "__main__":
    main()
