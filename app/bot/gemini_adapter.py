import asyncio
from google import genai
from google.genai import types

gemini_send_message_tool = {
    "name": "send_message_to_contact",
    "description": "Send a message to one of the owner's contacts on their behalf via Alter.",
    "parameters": {
        "type": "object",
        "properties": {
            "recipient_phone": {"type": "string"},
            "message_text": {"type": "string"},
        },
        "required": ["recipient_phone", "message_text"],
    },
}

gemini_owner_tools = [gemini_send_message_tool]

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
            
        gemini_messages.append(types.Content(role=role, parts=[types.Part.from_text(text=content)]))
        
    gemini_tool_objects = [
        types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"]
            )
            for t in tools
        ])
    ] if tools else []

    config = types.GenerateContentConfig(
        tools=gemini_tool_objects,
        system_instruction=system_prompt,
        temperature=0.7,
    )
    
    response = await asyncio.to_thread(
        client.models.generate_content,
        model='gemini-2.5-flash',
        contents=gemini_messages,
        config=config,
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
