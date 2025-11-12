"""Enhanced Markdown parsing and generation tool."""
import re
from typing import Dict, List, Tuple, Optional
from src.tools.base_tool import BaseTool

class MarkdownTool(BaseTool):
    """Tool for comprehensive Markdown analysis and generation."""
    
    def __init__(self):
        super().__init__("MarkdownTool")
        
        # Essential sections for professional READMEs
        self.essential_sections = {
            "installation": ["installation", "setup", "getting started", "quick start"],
            "usage": ["usage", "how to use", "basic usage"],
            "examples": ["examples", "example", "demo"],
            "documentation": ["documentation", "docs", "api reference"],
            "testing": ["testing", "tests", "running tests"],
            "contributing": ["contributing", "contribution guidelines"],
            "license": ["license", "licensing"],
        }
    
    def execute(self, content: str) -> Dict:
        """
        Comprehensive README analysis.
        
        Args:
            content: Markdown content
            
        Returns:
            Complete analysis dictionary
        """
        analysis = self._analyze_structure(content)
        analysis.update(self._analyze_content_quality(content))
        analysis.update(self._analyze_visual_elements(content))
        analysis["missing_sections"] = self._identify_missing_sections(analysis)
        analysis["quality_score"] = self._calculate_quality_score(analysis)
        
        return analysis
    
    def _analyze_structure(self, content: str) -> Dict:
        """Analyze structural elements of README."""
        structure = {
            # Title and headers
            "has_main_title": bool(re.search(r'^#\s+.+', content, re.MULTILINE)),
            "title": self._extract_title(content),
            "headers_h2": len(re.findall(r'^##\s+.+', content, re.MULTILINE)),
            "headers_h3": len(re.findall(r'^###\s+.+', content, re.MULTILINE)),
            
            # Sections
            "sections": self._extract_sections(content),
            "section_count": 0,  # Will be set below
            
            # Content length
            "word_count": len(content.split()),
            "char_count": len(content),
            "line_count": len(content.split('\n')),
        }
        
        structure["section_count"] = len(structure["sections"])
        
        # Check for essential sections
        for section_type, keywords in self.essential_sections.items():
            structure[f"has_{section_type}"] = self._has_section(content, keywords)
        
        return structure
    
    def _analyze_content_quality(self, content: str) -> Dict:
        """Analyze content quality indicators."""
        return {
            # Description and clarity
            "has_description": len(content) > 100,
            "has_detailed_description": len(content) > 500,
            "description_length": self._extract_description_length(content),
            
            # Documentation completeness
            "has_prerequisites": bool(re.search(
                r'(prerequisite|requirement|before you begin)',
                content,
                re.IGNORECASE
            )),
            "has_quickstart": bool(re.search(
                r'(quick\s*start|getting\s*started|tldr)',
                content,
                re.IGNORECASE
            )),
            "has_troubleshooting": bool(re.search(
                r'(troubleshoot|common\s*issue|faq)',
                content,
                re.IGNORECASE
            )),
            "has_configuration": bool(re.search(
                r'(configuration|config|environment)',
                content,
                re.IGNORECASE
            )),
        }
    
    def _analyze_visual_elements(self, content: str) -> Dict:
        """Analyze visual and formatting elements."""
        # Count badges
        badge_patterns = [
            r'!\[.*?\]\(https://img\.shields\.io',
            r'!\[.*?\]\(https://badge',
            r'\[!\[.*?\]\(.*?\)\]\(.*?\)',  # Linked badges
        ]
        badge_count = sum(len(re.findall(pattern, content)) for pattern in badge_patterns)
        
        # Count images
        image_count = len(re.findall(
            r'!\[.*?\]\(.*(png|jpg|jpeg|gif|svg|webp)',
            content,
            re.IGNORECASE
        ))
        
        # Code blocks
        code_blocks = re.findall(r'``````', content, re.DOTALL)
        
        return {
            # Badges and shields
            "has_badges": badge_count > 0,
            "badge_count": badge_count,
            "has_build_badge": bool(re.search(r'build|ci|tests.*passing', content, re.IGNORECASE)),
            "has_license_badge": bool(re.search(r'license.*badge', content, re.IGNORECASE)),
            "has_version_badge": bool(re.search(r'version|release', content, re.IGNORECASE)),
            
            # Visual content
            "has_images": image_count > 0,
            "image_count": image_count,
            "has_logo": bool(re.search(r'logo', content, re.IGNORECASE)),
            "has_screenshot": bool(re.search(r'screenshot', content, re.IGNORECASE)),
            "has_demo_gif": bool(re.search(r'\.(gif|mp4)', content, re.IGNORECASE)),
            
            # Code examples
            "has_code_blocks": len(code_blocks) > 0,
            "code_block_count": len(code_blocks),
            "code_languages": list(set(lang for lang, _ in code_blocks if lang)),
            
            # Formatting
            "has_tables": bool(re.search(r'\|.*\|.*\|', content)),
            "has_lists": bool(re.search(r'^\s*[-*+]\s+', content, re.MULTILINE)),
            "has_numbered_lists": bool(re.search(r'^\s*\d+\.\s+', content, re.MULTILINE)),
            "has_blockquotes": bool(re.search(r'^>\s+', content, re.MULTILINE)),
            "has_horizontal_rules": bool(re.search(r'^---+$', content, re.MULTILINE)),
            
            # Links
            "has_links": bool(re.search(r'\[.*?\]\(.*?\)', content)),
            "external_link_count": len(re.findall(r'\[.*?\]\(https?://.*?\)', content)),
            "has_table_of_contents": bool(re.search(
                r'(table\s+of\s+contents|toc|contents)',
                content,
                re.IGNORECASE
            )),
        }
    
    def _extract_title(self, content: str) -> Optional[str]:
        """Extract main title from README."""
        match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        return match.group(1).strip() if match else None
    
    def _extract_sections(self, content: str) -> List[str]:
        """Extract all section headers."""
        return re.findall(r'^##\s+(.+)$', content, re.MULTILINE)
    
    def _extract_description_length(self, content: str) -> int:
        """Extract length of description (content before first ## header)."""
        match = re.search(r'^#\s+.+\n\n(.*?)(?=\n##|\Z)', content, re.DOTALL | re.MULTILINE)
        if match:
            return len(match.group(1).split())
        return 0
    
    def _has_section(self, content: str, keywords: List[str]) -> bool:
        """Check if content has section matching any keyword."""
        pattern = '|'.join(keywords)
        return bool(re.search(rf'##\s*({pattern})', content, re.IGNORECASE))
    
    def _identify_missing_sections(self, analysis: Dict) -> List[str]:
        """Identify essential sections that are missing."""
        missing = []
        for section_type in self.essential_sections.keys():
            if not analysis.get(f"has_{section_type}", False):
                missing.append(section_type.replace('_', ' ').title())
        return missing
    
    def _calculate_quality_score(self, analysis: Dict) -> float:
        """
        Calculate overall README quality score (0-100).
        
        Scoring criteria:
        - Structure: 30 points
        - Content: 30 points
        - Visual elements: 20 points
        - Completeness: 20 points
        """
        score = 0.0
        
        # Structure score (30 points)
        if analysis.get("has_main_title"):
            score += 5
        if analysis.get("section_count", 0) >= 5:
            score += 10
        elif analysis.get("section_count", 0) >= 3:
            score += 5
        if analysis.get("word_count", 0) > 500:
            score += 10
        elif analysis.get("word_count", 0) > 200:
            score += 5
        if analysis.get("has_table_of_contents"):
            score += 5
        
        # Content score (30 points)
        content_checks = [
            "has_installation", "has_usage", "has_examples",
            "has_prerequisites", "has_configuration"
        ]
        score += sum(5 for check in content_checks if analysis.get(check, False))
        score = min(score, 60)  # Cap at 60 after structure + content
        
        # Visual elements (20 points)
        if analysis.get("badge_count", 0) >= 3:
            score += 5
        if analysis.get("has_code_blocks"):
            score += 5
        if analysis.get("image_count", 0) > 0:
            score += 5
        if analysis.get("has_tables"):
            score += 5
        
        # Completeness (20 points)
        completeness_checks = [
            "has_testing", "has_contributing", "has_license",
            "has_documentation"
        ]
        score += sum(5 for check in completeness_checks if analysis.get(check, False))
        
        return min(score, 100.0)
    
    def generate_improvement_suggestions(self, analysis: Dict) -> List[Dict]:
        """Generate specific improvement suggestions based on analysis."""
        suggestions = []
        
        # Title suggestions
        if not analysis.get("has_main_title"):
            suggestions.append({
                "category": "Structure",
                "priority": "High",
                "suggestion": "Add a clear, descriptive title using # heading",
                "example": "# My Awesome Project - Brief Description"
            })
        
        # Missing sections
        for missing in analysis.get("missing_sections", []):
            suggestions.append({
                "category": "Completeness",
                "priority": "High" if missing in ["Installation", "Usage"] else "Medium",
                "suggestion": f"Add a '{missing}' section",
                "example": f"## {missing}\n\n[Provide {missing.lower()} information here]"
            })
        
        # Badge suggestions
        if analysis.get("badge_count", 0) < 3:
            suggestions.append({
                "category": "Visual",
                "priority": "Medium",
                "suggestion": "Add badges for build status, license, and version",
                "example": "![Build](https://img.shields.io/badge/build-passing-brightgreen)"
            })
        
        # Code examples
        if not analysis.get("has_code_blocks"):
            suggestions.append({
                "category": "Content",
                "priority": "High",
                "suggestion": "Add code examples demonstrating usage",
                "example": "``````"
            })
        
        # Images
        if not analysis.get("has_images"):
            suggestions.append({
                "category": "Visual",
                "priority": "Medium",
                "suggestion": "Add screenshots or diagrams to illustrate functionality",
                "example": "![Demo](./docs/images/demo.png)"
            })
        
        # Table of contents
        if analysis.get("section_count", 0) > 5 and not analysis.get("has_table_of_contents"):
            suggestions.append({
                "category": "Structure",
                "priority": "Medium",
                "suggestion": "Add a table of contents for better navigation",
                "example": "## Table of Contents\n- [Installation](#installation)\n- [Usage](#usage)"
            })
        
        return suggestions
    
    def generate_section_template(self, section_name: str, content: str = "") -> str:
        """Generate formatted markdown section."""
        if not content:
            content = f"TODO: Add {section_name.lower()} information"
        
        return f"\n## {section_name}\n\n{content}\n"
