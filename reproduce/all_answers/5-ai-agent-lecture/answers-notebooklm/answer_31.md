The WBY voice assistant leverages function calling to perform actions on behalf of the user by combining multiple models and technologies. Here's how it works:

* **The user provides input in the form of speech.**
* **A speech-to-text model transcribes the speech.**
* **The transcribed speech is sent to a large language model (LLM).**
* **The LLM determines if it needs to use an external tool or API based on the user's input.** This decision-making process is called "function calling".
* **If the LLM determines that it needs to use a tool, it will select the appropriate tool and make the necessary API call.** Examples of tools include accessing calendar information, retrieving emails, and getting weather information.
* **The output from the tool is sent back to the LLM.**
* **The LLM combines the initial user input and the tool's output to generate a final response in text form.**
* **The text response is sent to a text-to-speech system.**
* **The generated speech is played back to the user.**

This modular approach allows WBY to connect to any tool, providing a comprehensive personal assistant experience. For example, if the user asks WBY to "check their calendar," the LLM will trigger the "get calendar events" function, retrieve the relevant information, and relay it back to the user in a spoken response.

Key features of WBY include:

* Support for multiple APIs, including proprietary and local models.
* A customizable system prompt that defines WBY's persona and capabilities.
* The use of efficient models like distilled Whisper large V3 for faster speech-to-text processing.

The developers are also planning to add support for local GPT models in the future.