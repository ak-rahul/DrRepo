from src.tools.github_tool import GitHubTool

print('🧪 Testing GitHub Tool...\n')

tool = GitHubTool()
data = tool.execute('https://github.com/psf/requests')

if 'error' not in data:
    print(f'✓ Repo: {data["name"]}')
    print(f'✓ Stars: {data["stars"]:,}')
    print(f'✓ Language: {data["language"]}')
    print(f'✓ Description: {data["description"][:50]}...')
    print(f'✓ Topics: {", ".join(data["topics"])}')
    print(f'\n✅ GitHub integration working!')
else:
    print(f'❌ Error: {data["error"]}')
