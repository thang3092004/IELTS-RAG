Anthropic introduced prompt caching as a new technique to reduce the cost of pre-processing data. Instead of downloading the entire model and then processing it, Anthropic splits the data into smaller chunks. This allows them to persist the model and pre-processing data for a certain amount of time. This is similar to Gemini's context caching. However, Anthropic's prompt caching has a few key differences:

- It persists for 48 hours, while Gemini's context caching is persistent for 2 hours. 
- Anthropic's prompt caching uses a smaller model, while Gemini uses a larger 3.5 billion model. 
- Anthropic's prompt caching is available for both API calls and local processing, while Gemini's context caching is only available for API calls.

In summary, Anthropic's prompt caching is a cost-efficient alternative to Gemini's context caching, with a shorter persistence time and smaller model size. It is available for API calls as well as local processing, while Gemini's context caching is only available for API calls.