Traditional RAG systems heavily rely on the **embedding model** to determine the relevant chunks for the LLM to generate responses. Therefore, selecting an appropriate chunking strategy and a high-quality embedding model is crucial for providing the LLM with sufficient context, even if a smaller LLM is used.

In contrast, Graph RAG utilizes LLMs more extensively, making the **choice of LLM even more critical** than in traditional RAG. The process involves:

- **Entity and relationship extraction:** A powerful LLM is needed to accurately identify entities and their relationships within documents, forming the basis of the knowledge graph. Using a smaller LLM may result in an inaccurate graph, leading to subpar responses.
- **Community summarization:** LLMs are used to create summaries of communities within the knowledge graph, further emphasizing the importance of LLM quality for accurate representation.

Essentially, Graph RAG employs LLMs for multiple stages, including graph creation and summarization, whereas traditional RAG primarily uses the LLM for response generation based on retrieved chunks. This distinction makes the selection of a powerful and capable LLM more crucial in Graph RAG compared to traditional RAG.

It is also important to note that prompt engineering plays a significant role in both systems, with different LLMs reacting differently to the same prompt. Tailoring prompts for specific LLMs used in both traditional and Graph RAG systems is essential for achieving optimal performance.