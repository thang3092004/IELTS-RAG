Anthropic and Gemini have different approaches to caching, which can significantly impact the cost and performance of their models. 

Anthropic uses contextual caching, where the model is trained on a large dataset and the model's predictions are stored and reused for subsequent queries. This allows them to reduce the number of API calls required, which can save up to 90% of the cost. However, this approach requires retraining the model and re-indexing the data. 

Gemini uses a different approach called "prompt caching", where they pre-process the data and store the model's predictions in a cache. This allows them to reuse the model's predictions for subsequent queries without retraining. However, this approach does not preserve the original context information and requires more VRAM to store the pre-processed data. 

In summary, Gemini's prompt caching approach is more efficient in terms of cost, while Anthropic's contextual caching requires retraining the model and re-indexing the data, but can save up to 90% of the cost. The choice depends on the specific use case and available resources.