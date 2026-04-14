Late chunking is a technique that can significantly enhance the accuracy of retrieval systems by preserving contextual information within a document.

Here's how late chunking works:

* **Traditional Chunking and Embedding:** In standard retrieval augmented generation (RAG) pipelines, a document is first divided into smaller chunks, and then each chunk is passed through a transformer model to generate embeddings. This process results in the loss of contextual information as each chunk is treated independently.
* **Late Chunking Process:** Late chunking reverses this process. Instead of chunking first, the entire document is passed through a transformer model to generate embeddings for each token. These token embeddings contain contextual information from the entire document. Afterward, the document is divided into chunks, and the corresponding token embeddings are used to compute the final representation for each chunk. This approach ensures that the final chunk embeddings retain the rich contextual information from the whole document.

**Benefits of Late Chunking:**

* **Preserves Contextual Information:** By embedding the entire document before chunking, late chunking ensures that each chunk's embedding incorporates the context of the entire document, leading to more accurate retrieval results.
* **Improved Similarity Scores:** Late chunking leads to higher similarity scores for chunks that refer to a concept indirectly, as the embeddings capture the context from the entire document.
* **Efficient Storage:** Late chunking does not significantly increase storage needs compared to traditional chunking methods.
* **Bidirectional Context:** Late chunking considers information both before and after a specific chunk, allowing for a more comprehensive understanding of the context.

**Importance of Long Context Embedding Models:**

* **Context Window:** Late chunking relies on embedding models with a long context window to process the entire document before chunking.
* **Jenna Embeddings:** Jenna AI's embedding models, specifically Jenna Embeddings version 3 with an 8,000-token context window, are well-suited for late chunking. This allows for embedding approximately ten pages of text while preserving contextual information.

**Comparison with Contextual Retrieval:**

* **Contextual Retrieval:** Anthropic's contextual retrieval technique attempts to address context loss by summarizing the document and adding contextual information to each chunk using an LLM. However, it is computationally expensive and still limited by chunking boundaries.
* **Late Chunking Advantage:** Late chunking is a more efficient approach as it does not require an LLM to add context to each chunk. It also appears to be less sensitive to chunking boundaries, leading to more accurate retrieval results.

**Conclusion:**

Late chunking is a powerful technique that leverages long context embedding models to significantly enhance retrieval system accuracy by preserving crucial contextual information. Its efficiency and effectiveness make it a compelling alternative to traditional chunking methods and other context enhancement techniques like contextual retrieval.