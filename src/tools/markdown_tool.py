"""Markdown analysis tool for README files."""
import re
from typing import Dict, List


class MarkdownTool:
    """Tool for analyzing markdown content."""
    
    def execute(self, content: str) -> Dict:
        """Analyze markdown content and return metrics."""
        if not content:
            return self._empty_analysis()
        
        analysis = {
            "word_count": self._count_words(content),
            "section_count": self._count_sections(content),
            "code_block_count": self._count_code_blocks(content),
            "image_count": self._count_images(content),
            "link_count": self._count_links(content),
            "badge_count": self._count_badges(content),
            "missing_sections": self._find_missing_sections(content),
            "has_table_of_contents": self._has_toc(content),
            "quality_score": 0
        }
        
        analysis["quality_score"] = self._calculate_quality_score(analysis)
        return analysis
    
    def generate_improvement_suggestions(self, analysis: Dict) -> List[Dict]:
        """Generate improvement suggestions."""
        suggestions = []
        
        if analysis.get("word_count", 0) < 300:
            suggestions.append({
                "priority": "high",
                "suggestion": "README is too short. Add more detailed explanation."
            })
        
        if analysis.get("code_block_count", 0) == 0:
            suggestions.append({
                "priority": "high",
                "suggestion": "Add code examples."
            })
        
        if analysis.get("image_count", 0) == 0:
            suggestions.append({
                "priority": "medium",
                "suggestion": "Add screenshots or diagrams."
            })
        
        if not analysis.get("has_table_of_contents", False) and analysis.get("section_count", 0) > 5:
            suggestions.append({
                "priority": "medium",
                "suggestion": "Add table of contents."
            })
        
        if analysis.get("badge_count", 0) == 0:
            suggestions.append({
                "priority": "low",
                "suggestion": "Add badges."
            })
        
        return suggestions
    
    def _empty_analysis(self) -> Dict:
        """Return empty analysis."""
        return {
            "word_count": 0,
            "section_count": 0,
            "code_block_count": 0,
            "image_count": 0,
            "link_count": 0,
            "badge_count": 0,
            "missing_sections": ["All sections missing"],
            "has_table_of_contents": False,
            "quality_score": 0
        }
    
    def _count_words(self, content: str) -> int:
        """Count words."""
        content = re.sub(r'``````', '', content, flags=re.DOTALL)
        return len(content.split())
    
    def _count_sections(self, content: str) -> int:
        """Count markdown sections."""
        return len(re.findall(r'^#{1,6}\s+.+$', content, re.MULTILINE))
    
    def _count_code_blocks(self, content: str) -> int:
        """Count code blocks."""
        return len(re.findall(r'```', content)) // 2

    
    def _count_images(self, content: str) -> int:
        """Count images."""
        return len(re.findall(r'!$$.*?$$$$.*?$$', content))
    
    def _count_links(self, content: str) -> int:
        """Count links."""
        return len(re.findall(r'$$.*?$$$$.*?$$', content))
    
    def _count_badges(self, content: str) -> int:
        """Count badges."""
        return len(re.findall(r'!$$.*?$$$$https?://.*?badge.*?$$', content, re.IGNORECASE))
    
    def _has_toc(self, content: str) -> bool:
        """Check if has table of contents."""
        toc_patterns = [
            r'## Table of Contents',
            r'## Contents',
            r'## TOC',
            r'\* $$.*?$$$$#.*?$$'
        ]
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in toc_patterns)
    
    def _find_missing_sections(self, content: str) -> List[str]:
        """Find missing sections."""
        content_lower = content.lower()
        
        essential_sections = {
            "installation": ["install", "setup", "getting started"],
            "usage": ["usage", "how to use", "quick start"],
            "features": ["features", "capabilities"],
            "documentation": ["documentation", "docs", "api"],
            "contributing": ["contributing", "contribution"],
            "license": ["license"],
            "examples": ["examples", "demo"]
        }
        
        missing = []
        for section, keywords in essential_sections.items():
            if not any(keyword in content_lower for keyword in keywords):
                missing.append(section.title())
        
        return missing
    
    def _calculate_quality_score(self, analysis: Dict) -> float:
        """Calculate quality score 0-100."""
        score = 0
        
        # Word count (20 points)
        word_count = analysis.get("word_count", 0)
        if word_count >= 1000:
            score += 20
        elif word_count >= 500:
            score += 15
        elif word_count >= 300:
            score += 10
        elif word_count >= 100:
            score += 5
        
        # Sections (20 points)
        section_count = analysis.get("section_count", 0)
        score += min(section_count * 3, 20)
        
        # Code examples (15 points)
        code_count = analysis.get("code_block_count", 0)
        score += min(code_count * 5, 15)
        
        # Images (10 points)
        image_count = analysis.get("image_count", 0)
        score += min(image_count * 3, 10)
        
        # Missing sections penalty (-30 points max)
        missing = analysis.get("missing_sections", [])
        score -= min(len(missing) * 5, 30)
        
        # Table of contents (5 points)
        if analysis.get("has_table_of_contents", False):
            score += 5
        
        # Badges (5 points)
        if analysis.get("badge_count", 0) > 0:
            score += 5
        
        # Links (10 points)
        link_count = analysis.get("link_count", 0)
        score += min(link_count * 2, 10)
        
        return max(0, min(100, score))
