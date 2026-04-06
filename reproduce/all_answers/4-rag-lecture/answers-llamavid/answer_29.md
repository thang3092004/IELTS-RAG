Prompt caching is a technique used to reduce the cost of running API calls for cloud-based models. When a user prompts a model, the model retrieves the information and generates a response. However, after retrieving the information, the model may not need to use it for subsequent prompts. 

Prompt caching works by storing the retrieved information in a cache so that it can be reused for subsequent prompts. This can significantly reduce the cost of retrieving the same information multiple times, as the information can be retrieved from the cache instead of from the API.

For example, if a user prompts a model to retrieve information about a company, the model retrieves the information and generates a response. The information is then stored in the cache so that the model can retrieve the information again for subsequent prompts related to the same company. This allows the model to retrieve the same information multiple times at a much lower cost.

Prompt caching is implemented by using a cache key to identify the information that was previously retrieved and stored in the cache. The cache key is based on the user's prompt and the model's index. The model then retrieves the stored information from the cache, instead of calling the API again. This significantly reduces the cost of running the API call.

Prompt caching is a technique used by cloud-based models like Gemini and other large language models. It is implemented using API endpoints and cache keys to store the retrieved information in the cache.