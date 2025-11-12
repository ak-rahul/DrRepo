from src.tools.github_tool import GitHubTool
from src.tools.markdown_tool import MarkdownTool

print('🧪 Testing README Analysis...\n')

# Fetch repo
github_tool = GitHubTool()
data = github_tool.execute('https://github.com/psf/requests')

if 'error' in data:
    print(f'❌ Error: {data["error"]}')
else:
    # Analyze README
    markdown_tool = MarkdownTool()
    analysis = markdown_tool.execute(data['readme_content'])
    
    print(f'📊 README Analysis for: {data["name"]}')
    print(f'{"="*60}')
    print(f'Quality Score: {analysis["quality_score"]:.1f}/100')
    print(f'Word Count: {analysis["word_count"]}')
    print(f'Sections: {analysis["section_count"]}')
    print(f'Has Installation: {analysis["has_installation"]}')
    print(f'Has Usage: {analysis["has_usage"]}')
    print(f'Has Examples: {analysis["has_examples"]}')
    print(f'Code Blocks: {analysis.get("code_block_count", 0)}')
    print(f'Images: {analysis.get("image_count", 0)}')
    print(f'Badges: {analysis.get("badge_count", 0)}')
    
    print(f'\n❌ Missing Sections:')
    for section in analysis.get('missing_sections', []):
        print(f'  - {section}')
    
    print(f'\n✅ Analysis complete!')
