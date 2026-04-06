When using local LLMs with MemGPT, some technical challenges may arise:

* **MemGPT requires LLMs that support function calling.**  MemGPT relies on function calling to perform various operations. Therefore, the local LLM must have the capability to handle function calls. Smaller models may not work as well because they may not be able to perform function calling effectively.

* **Setting up the API server for the local LLM can be complex.** To use a local LLM with MemGPT, you need to serve it through an API. The process involves several steps, including loading the LLM, configuring the API server, and connecting it to MemGPT.

* **Performance can be an issue, especially with larger models.**  Using a 70B parameter model with MemGPT can lead to slower response times due to its size.  The hardware used to run the local LLM can significantly impact performance.  Factors like the number of CPU threads, batch size, and GPU usage all need to be optimized for best results.

* **Compatibility issues can occur.** MemGPT primarily uses OpenAI's GPT models. While it now supports local LLMs, compatibility is still an ongoing development. There might be instances where MemGPT's functionalities do not interact seamlessly with certain local LLMs.

* **Limited community support and documentation.** While there are instructions available, they may not be comprehensive. As the use of local LLMs with MemGPT is relatively new, there is limited community support or readily available troubleshooting resources. This can make it difficult to resolve issues that arise.

Overall, using local LLMs with MemGPT offers benefits such as privacy and cost savings. However, it's important to be aware of the potential technical hurdles and ensure that your setup and model choice are appropriate to mitigate these challenges.