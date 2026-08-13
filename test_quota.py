import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

try:
    print("Calling gemini-3.5-flash...")
    response = client.models.generate_content(model="gemini-3.5-flash", contents="Hello")
    print("Success:", response.text)
except Exception as e:
    print("Exception type:", type(e))
    print("Exception details:", str(e))
