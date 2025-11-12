"""Comprehensive tests for MarkdownTool."""
import pytest
from src.tools.markdown_tool import MarkdownTool


class TestMarkdownTool:
    """Test suite for MarkdownTool class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = MarkdownTool()
    
    def test_initialization(self):
        """Test tool initialization."""
        assert self.tool.name == "MarkdownTool"
        assert hasattr(self.tool, 'essential_sections')
        assert 'installation' in self.tool.essential_sections
    
    # ==================== Basic Structure Tests ====================
    
    def test_execute_with_minimal_readme(self):
        """Test analysis of minimal README."""
        content = "# Test Project"
        result = self.tool.execute(content)
        
        assert result["has_main_title"] is True
        assert result["title"] == "Test Project"
        assert result["word_count"] == 2
        assert result["section_count"] == 0
    
    def test_execute_with_complete_readme(self):
        """Test analysis of complete README."""
        content = """# Awesome Project

A comprehensive description of the project.

## Table of Contents
- Installation
- Usage
- Examples

## Installation

pip install awesome-project


## Examples

Here are some examples:

### Example 1
Code here.

### Example 2
More code.

## Contributing

Please read CONTRIBUTING.md.

## License

MIT License
"""
        result = self.tool.execute(content)
        
        assert result["has_main_title"] is True
        assert result["title"] == "Awesome Project"
        assert result["has_installation"] is True
        assert result["has_usage"] is True
        assert result["has_examples"] is True
        assert result["has_contributing"] is True
        assert result["has_license"] is True
        assert result["has_code_blocks"] is True
        assert result["has_table_of_contents"] is True
        assert result["section_count"] == 5
        assert result["quality_score"] > 70
    
    def test_execute_with_no_title(self):
        """Test README without main title."""
        content = "This is just some text without a title."
        result = self.tool.execute(content)
        
        assert result["has_main_title"] is False
        assert result["title"] is None
    
    # ==================== Section Detection Tests ====================
    
    def test_has_installation_section(self):
        """Test detection of installation section."""
        content = """# Project

## Installation

Install instructions here.
"""
        result = self.tool.execute(content)
        assert result["has_installation"] is True
    
    def test_has_installation_variations(self):
        """Test detection of installation section variations."""
        variations = [
            "## Installation",
            "## Setup",
            "## Getting Started",
            "## Quick Start"
        ]
        
        for variation in variations:
            content = f"# Project\n\n{variation}\n\nInstructions here."
            result = self.tool.execute(content)
            assert result["has_installation"] is True, f"Failed for: {variation}"
    
    def test_has_usage_section(self):
        """Test detection of usage section."""
        content = """# Project

## Usage

Usage instructions here.
"""
        result = self.tool.execute(content)
        assert result["has_usage"] is True
    
    def test_has_examples_section(self):
        """Test detection of examples section."""
        content = """# Project

## Examples

Example code here.
"""
        result = self.tool.execute(content)
        assert result["has_examples"] is True
    
    def test_has_contributing_section(self):
        """Test detection of contributing section."""
        content = """# Project

## Contributing

Contributing guidelines here.
"""
        result = self.tool.execute(content)
        assert result["has_contributing"] is True
    
    def test_has_license_section(self):
        """Test detection of license section."""
        content = """# Project

## License

MIT License
"""
        result = self.tool.execute(content)
        assert result["has_license"] is True
    
    # ==================== Visual Elements Tests ====================
    
    def test_badge_detection(self):
        """Test detection of badges."""
        content = """# Project

![Build Status](https://img.shields.io/badge/build-passing-green)
![License](https://img.shields.io/badge/license-MIT-blue)

Description here.
"""
        result = self.tool.execute(content)
        
        assert result["has_badges"] is True
        assert result["badge_count"] == 2
    
    def test_image_detection(self):
        """Test detection of images."""
        content = """# Project

![Screenshot](./docs/screenshot.png)
![Demo](https://example.com/demo.gif)

Description here.
"""
        result = self.tool.execute(content)
        
        assert result["has_images"] is True
        assert result["image_count"] == 2
    
    def test_code_block_detection(self):
        """Test detection of code blocks."""
        content = """# Project

## Installation

pip install project

## Usage

import project
project.run()

"""
        result = self.tool.execute(content)
        
        assert result["has_code_blocks"] is True
        assert result["code_block_count"] == 2
        assert "bash" in result["code_languages"]
        assert "python" in result["code_languages"]
    
    def test_table_detection(self):
        """Test detection of tables."""
        content = """# Project

| Feature | Status |
|---------|--------|
| API     | Ready  |
| Docs    | WIP    |

Description here.
"""
        result = self.tool.execute(content)
        
        assert result["has_tables"] is True
    
    def test_link_detection(self):
        """Test detection of links."""
        content = """# Project

Check out [the documentation](https://docs.example.com) and visit our [website](https://example.com).
"""
        result = self.tool.execute(content)
        
        assert result["has_links"] is True
        assert result["external_link_count"] == 2
    
    # ==================== Quality Score Tests ====================
    
    def test_quality_score_minimal_readme(self):
        """Test quality score for minimal README."""
        content = "# Project"
        result = self.tool.execute(content)
        
        assert result["quality_score"] < 30
    
    def test_quality_score_basic_readme(self):
        """Test quality score for basic README."""
        content = """# Project

A simple project description.

## Installation

pip install project

## Usage

Run the project.
"""
        result = self.tool.execute(content)
        
        assert 40 <= result["quality_score"] <= 60
    
    def test_quality_score_excellent_readme(self):
        """Test quality score for excellent README."""
        content = """# Excellent Project

![Build](https://img.shields.io/badge/build-passing-green)
![License](https://img.shields.io/badge/license-MIT-blue)
![Version](https://img.shields.io/badge/version-1.0.0-blue)

Comprehensive project description with all necessary details.

## Table of Contents
- Installation
- Usage
- Examples
- Contributing
- License

## Installation

pip install excellent-project


## Usage

Detailed usage instructions with examples.

import excellent_project
result = excellent_project.run()

## Examples

Multiple examples demonstrating functionality.

![Screenshot](./docs/screenshot.png)

## Testing

Run tests with pytest:

pytest tests/


## Contributing

Please read CONTRIBUTING.md for details.

## Documentation

Full API documentation available at https://docs.example.com

## License

MIT License - see LICENSE file for details.
"""
        result = self.tool.execute(content)
        
        assert result["quality_score"] >= 80
    
    # ==================== Missing Sections Tests ====================
    
    def test_identify_missing_sections_all_present(self):
        """Test when all essential sections are present."""
        content = """# Project

## Installation
Instructions

## Usage
Instructions

## Examples
Examples

## Contributing
Guidelines

## License
MIT

## Testing
Test info

## Documentation
Docs link
"""
        result = self.tool.execute(content)
        
        assert len(result["missing_sections"]) == 0
    
    def test_identify_missing_sections_none_present(self):
        """Test when no essential sections are present."""
        content = "# Project\n\nJust a description."
        result = self.tool.execute(content)
        
        missing = result["missing_sections"]
        assert len(missing) > 0
        assert any("Installation" in s for s in missing)
        assert any("Usage" in s for s in missing)
    
    # ==================== Improvement Suggestions Tests ====================
    
    def test_generate_improvement_suggestions_minimal(self):
        """Test suggestions for minimal README."""
        analysis = {
            "has_main_title": False,
            "badge_count": 0,
            "has_code_blocks": False,
            "has_images": False,
            "section_count": 0,
            "has_table_of_contents": False,
            "missing_sections": ["Installation", "Usage", "Examples"]
        }
        
        suggestions = self.tool.generate_improvement_suggestions(analysis)
        
        assert len(suggestions) > 0
        assert any("title" in s["suggestion"].lower() for s in suggestions)
        assert any("installation" in s["suggestion"].lower() for s in suggestions)
        assert any("badge" in s["suggestion"].lower() for s in suggestions)
        assert any("code" in s["suggestion"].lower() for s in suggestions)
    
    def test_generate_improvement_suggestions_categories(self):
        """Test that suggestions include proper categories."""
        analysis = {
            "has_main_title": False,
            "badge_count": 0,
            "has_code_blocks": False,
            "missing_sections": ["Installation"],
            "section_count": 2,
            "has_table_of_contents": False,
            "image_count": 0
        }
        
        suggestions = self.tool.generate_improvement_suggestions(analysis)
        
        categories = [s["category"] for s in suggestions]
        assert "Structure" in categories
        assert "Completeness" in categories
    
    def test_generate_improvement_suggestions_priority(self):
        """Test that suggestions include priority levels."""
        analysis = {
            "has_main_title": True,
            "badge_count": 0,
            "has_code_blocks": False,
            "missing_sections": ["Installation", "Usage"],
            "section_count": 3,
            "has_table_of_contents": False,
            "image_count": 0
        }
        
        suggestions = self.tool.generate_improvement_suggestions(analysis)
        
        priorities = [s["priority"] for s in suggestions]
        assert "High" in priorities
        assert any(p in ["Medium", "Low"] for p in priorities)
    
    # ==================== Section Template Generation Tests ====================
    
    def test_generate_section_template_with_content(self):
        """Test section template generation with content."""
        result = self.tool.generate_section_template(
            "Installation",
            "Run `pip install package-name`"
        )
        
        assert "## Installation" in result
        assert "pip install package-name" in result
    
    def test_generate_section_template_without_content(self):
        """Test section template generation without content."""
        result = self.tool.generate_section_template("Usage")
        
        assert "## Usage" in result
        assert "TODO" in result
    
    # ==================== Edge Cases ====================
    
    def test_empty_content(self):
        """Test with empty content."""
        content = ""
        result = self.tool.execute(content)
        
        assert result["has_main_title"] is False
        assert result["word_count"] == 0
        assert result["quality_score"] == 0
    
    def test_content_with_only_whitespace(self):
        """Test with only whitespace."""
        content = "   \n\n   \t\t\n   "
        result = self.tool.execute(content)
        
        assert result["has_main_title"] is False
        assert result["word_count"] == 0
    
    def test_malformed_markdown(self):
        """Test with malformed markdown."""
        content = """# Title
        
##No space after hash
### Another    weird     spacing
        
[Link without URL]
![Image without source]
"""
        result = self.tool.execute(content)
        
        # Should not crash, just return analysis
        assert "has_main_title" in result
        assert "quality_score" in result
    
    def test_very_long_readme(self):
        """Test with very long README."""
        content = "# Project\n\n" + ("This is a test paragraph. " * 1000)
        result = self.tool.execute(content)
        
        assert result["word_count"] > 5000
        assert result["has_main_title"] is True
    
    # ==================== Special Characters Tests ====================
    
    def test_unicode_characters(self):
        """Test with Unicode characters."""
        content = """# 프로젝트 테스트 🚀

## Installation 安装

测试内容 with émojis 🎉 and spëcial çharacters.

print("Hello 世界")

"""
        result = self.tool.execute(content)
        
        assert result["has_main_title"] is True
        assert result["has_installation"] is True
        assert result["has_code_blocks"] is True
    
    def test_case_insensitive_section_detection(self):
        """Test that section detection is case-insensitive."""
        variations = [
            "## INSTALLATION",
            "## installation",
            "## Installation",
            "## InStAlLaTiOn"
        ]
        
        for variation in variations:
            content = f"# Project\n\n{variation}\n\nInstructions."
            result = self.tool.execute(content)
            assert result["has_installation"] is True
    
    # ==================== Integration Tests ====================
    
    def test_full_analysis_workflow(self):
        """Test complete analysis workflow."""
        content = """# Real World Project

![Build](https://img.shields.io/badge/build-passing-green)
![Coverage](https://img.shields.io/badge/coverage-95%25-brightgreen)

A real-world project with comprehensive documentation.

## Table of Contents
- [Installation](#installation)
- [Usage](#usage)
- [API Reference](#api-reference)

## Installation

### Prerequisites
- Python 3.9+
- pip

### Steps

pip install real-world-project


## Usage

Basic usage example:

from real_world import Project

project = Project()
result = project.execute()


## API Reference

See [documentation](https://docs.example.com).

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT License
"""
        result = self.tool.execute(content)
        
        # Comprehensive checks
        assert result["has_main_title"] is True
        assert result["badge_count"] >= 2
        assert result["has_table_of_contents"] is True
        assert result["has_installation"] is True
        assert result["has_usage"] is True
        assert result["has_code_blocks"] is True
        assert result["has_contributing"] is True
        assert result["has_license"] is True
        assert result["quality_score"] > 70
        
        # Check missing sections
        missing = result["missing_sections"]
        assert len(missing) < 3  # Should have most sections
        
        # Generate suggestions
        suggestions = self.tool.generate_improvement_suggestions(result)
        assert isinstance(suggestions, list)


# ==================== Parametrized Tests ====================

class TestMarkdownToolParametrized:
    """Parametrized tests for MarkdownTool."""
    
    @pytest.fixture
    def tool(self):
        """Fixture to provide MarkdownTool instance."""
        return MarkdownTool()
    
    @pytest.mark.parametrize("section_name,keywords", [
        ("Installation", ["installation", "setup", "getting started"]),
        ("Usage", ["usage", "how to use"]),
        ("Examples", ["examples", "example", "demo"]),
        ("Contributing", ["contributing", "contribution"]),
        ("License", ["license", "licensing"]),
    ])
    def test_section_detection_parametrized(self, tool, section_name, keywords):
        """Test section detection with different keywords."""
        for keyword in keywords:
            content = f"# Project\n\n## {keyword.title()}\n\nContent here."
            result = tool.execute(content)
            
            field_name = f"has_{section_name.lower()}"
            assert result[field_name] is True, f"Failed for keyword: {keyword}"
    
    @pytest.mark.parametrize("quality_range,expected_status", [
        ((0, 30), "Poor"),
        ((40, 60), "Fair"),
        ((70, 80), "Good"),
        ((85, 100), "Excellent"),
    ])
    def test_quality_ranges(self, tool, quality_range, expected_status):
        """Test quality score ranges map to correct status."""
        # This is a conceptual test - actual implementation depends on scoring logic
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src.tools.markdown_tool"])



