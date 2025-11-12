"""Tests for MarkdownTool."""
import pytest
from src.tools.markdown_tool import MarkdownTool

class TestMarkdownTool:
    
    def test_initialization(self):
        """Test tool initialization."""
        tool = MarkdownTool()
        assert tool.name == "MarkdownTool"
    
    def test_execute_with_basic_readme(self):
        """Test analysis of basic README."""
        tool = MarkdownTool()
        content = """# Test Project

This is a test project.

## Installation

pip install test

## Usage

Run the tests.
"""
        result = tool.execute(content)
        
        assert result["has_main_title"] is True
        assert result["title"] == "Test Project"
        assert result["has_installation"] is True
        assert result["has_usage"] is True
        assert result["section_count"] == 2
    
    def test_quality_score_calculation(self):
        """Test quality score calculation."""
        tool = MarkdownTool()
        content = """
        # Excellent Project

Comprehensive description with details.

## Table of Contents
- Installation
- Usage

## Installation

