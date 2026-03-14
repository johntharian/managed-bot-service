from google import genai
from google.genai import types

gemini_tools = [
    {
        "name": "gmail_read_inbox",
        "description": "Read the recent emails from the user's Gmail inbox.",
        "parameters": {
            "type": "object",
            "properties": {"max_results": {"type": "integer"}},
        }
    },
    {
        "name": "gcal_create_event",
        "description": "Create a new event on the user's Google Calendar.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"}
            },
            "required": ["summary", "start_time", "end_time"]
        }
    }
]

async def call_gemini(api_key: str, system_prompt: str, messages: list, tools: list) -> dict:
    client = genai.Client(api_key=api_key)
    
    # Format messages for Gemini
    # ContextAssembler gives us [{'role': 'user', 'content': ...}]
    gemini_messages = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        
        # If content is a dict (like the webhook envelope), dump to string
        content = msg["content"]
        if isinstance(content, dict):
            import json
            content = json.dumps(content)
            
        gemini_messages.append(types.Content(role=role, parts=[types.Part.from_text(content)]))
        
    config = types.GenerateContentConfig(
        tools=tools, # Pass our tools list
        system_instruction=system_prompt,
        temperature=0.7,
    )
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=gemini_messages,
        config=config
    )
    
    # Parse for tools vs text
    if response.function_calls:
        # Just grab the first tool call
        fc = response.function_calls[0]
        return {
            "type": "tool_call",
            "name": fc.name,
            "args": {k: v for k, v in fc.args.items()}
        }
    else:
        return {
            "type": "text",
            "content": response.text
        }
