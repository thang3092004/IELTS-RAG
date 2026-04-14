Late chunking, a technique used in retrieval augmented generation (RAG) systems, offers potential benefits and drawbacks in terms of retrieval effectiveness and computational cost:

**Benefits**:

* **Enhanced Contextual Information**: Late chunking involves embedding the entire document first, then dividing it into chunks. This allows each token embedding to contain contextual information from the entire document, leading to richer and more informative embeddings. This approach preserves bidirectional context, meaning that even if relevant information appears before or after a specific chunk, the chunk's embedding will retain some information about it.
* **Improved Retrieval Accuracy**: By preserving contextual information, late chunking can significantly boost retrieval accuracy, especially when dealing with sentences or chunks that indirectly refer to the search query. Studies show that late chunking, combined with suitable embedding models, can yield state-of-the-art results in retrieval tasks.
* **Efficient Storage**: Late chunking offers similar storage requirements to naive chunking approaches, unlike late interaction methods like Colbert, which demand significantly more storage.

**Drawbacks**:

* **Computational Demands**: Embedding an entire document before chunking necessitates using embedding models with a long context window, capable of processing thousands of tokens. Such models often require substantial computational resources and memory, which might not be feasible for all users. For example, the multilingual gamma 2 embedding model needs about 34 GB of VRAM.
* **Dependence on Embedding Model**: The effectiveness of late chunking is heavily reliant on the chosen embedding model. While models like Jenna Embeddings v3 with an 8,000-token context window show promising results, selecting the appropriate model is crucial.

**Overall**:

Late chunking presents a promising approach for enhancing retrieval effectiveness in RAG systems, particularly when handling documents with implicit references and complex contextual relationships. However, its computational demands and reliance on suitable embedding models should be carefully considered before implementation. Developers must weigh these trade-offs and evaluate the suitability of late chunking for their specific applications and resource constraints.