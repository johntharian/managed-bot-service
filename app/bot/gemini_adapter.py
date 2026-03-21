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

        content = msg["content"]
        if isinstance(content, dict):
            import json
            content = json.dumps(content)

        # Gemini rejects empty Parts — replace blank content (e.g. media-only messages) with a placeholder
        if not content or not str(content).strip():
            content = "[media message]"

        gemini_messages.append(types.Content(role=role, parts=[types.Part.from_text(text=str(content))]))
        
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
        # response.text can be None when the model produces only thinking tokens
        text = response.text
        if not text:
            # Attempt to extract text from candidates directly
            try:
                parts = response.candidates[0].content.parts
                text = "\n".join(p.text for p in parts if hasattr(p, "text") and p.text)
            except Exception:
                pass
        return {
            "type": "text",
            "content": text or "",
        }
