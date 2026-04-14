Chunking is the process of dividing text into smaller units for embedding and storage in a vector database. Chunking strategies impact the performance and cost of Retrieval Augmented Generation (RAG) systems.

The sources discuss several chunking methods. **Traditional RAG systems often use naive chunking, which divides text into equal-sized chunks without considering semantic relationships**. This can lead to a loss of context. For example, if a sentence refers to an entity mentioned in a previous chunk, the isolated chunk may lose that context.

**To address context loss, Anthropic proposes contextual retrieval, which uses an LLM to add contextual information to each chunk.** The LLM situates the chunk within the document, providing relevant background information. This approach can be computationally expensive, but prompt caching can reduce the cost.

**Late chunking, proposed by Jenna AI, offers an alternative approach to preserving context.** Instead of chunking before embedding, late chunking embeds the entire document first, capturing contextual information at the token level. Chunking occurs after embedding, preserving context within the chunks. This method provides a balance between accuracy and storage needs.

**Other chunking strategies include**:

* **Sentence level chunking:** Dividing text at sentence boundaries. While simple, this approach can lead to context fragmentation.
* **Semantic chunking:** Dividing text based on semantic meaning, often using natural language processing techniques. This method can be more complex but potentially improves retrieval accuracy.
* **Recursive character chunking:** A technique from Langchain that splits text based on paragraphs, sentences, and characters.

The choice of chunking strategy depends on factors like document length, desired accuracy, and computational resources. The sources emphasize the importance of evaluating different chunking methods and customizing them for specific applications.

The sources also discuss **the impact of long context models on chunking.** Long context models, such as those from Jenna AI, can process large amounts of text, allowing for late chunking with minimal context loss. These models enhance the effectiveness of late chunking, improving retrieval accuracy while maintaining reasonable storage needs.