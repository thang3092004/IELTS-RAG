import os
import asyncio
from openai import AsyncOpenAI, BadRequestError

async def test_tool_calls_none():
    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!", "tool_calls": None}
    ]
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
        print("Success with tool_calls=None")
    except BadRequestError as e:
        print(f"Failed with tool_calls=None: {e}")

if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set")
    else:
        asyncio.run(test_tool_calls_none())
