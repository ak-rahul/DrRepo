import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

print('🧪 Testing Groq Integration...\n')

# Load environment
load_dotenv()

groq_key = os.getenv('GROQ_API_KEY')
if not groq_key:
    print('❌ GROQ_API_KEY not found in .env')
    exit(1)

print(f'✓ API Key loaded: {groq_key[:20]}...')

# Test Groq
try:
    llm = ChatGroq(
        model='llama-3.1-70b-versatile',
        temperature=0.3,
        api_key=groq_key
    )
    
    response = llm.invoke('Say hello and confirm you are working, in one sentence.')
    print(f'\n✓ Groq Response: {response.content}')
    print('\n✅ Groq integration working perfectly!')
    
except Exception as e:
    print(f'\n❌ Error: {e}')
