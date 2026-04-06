Here are some methods used to improve LLM retrieval accuracy, as discussed in the sources:

* **Chunking and embedding experiments** can result in a 50% increase in retrieval accuracy.
* Adding a **reranking and classification step** can further boost accuracy.
* **Query expansion** is a critical component because it allows the LLM to rewrite a user's question, leading to better questions and thus, better retrieval.
* **Tool usage or function calling** can provide more context to the LLM.
* **Prompt engineering**
* **Fine-tuning embedding models** can provide a performance boost.
* **Hypothetical document embedding retrieval (HyDE)**

It is important to note that using **cosign similarity**, which is used in a standard retrieval augmented generation (RAG) system, only provides 45% retrieval accuracy.

The sources also recommend **evaluating and testing each step** of the retrieval system. For example, when building a RAG system, one should ensure that the correct chunks are retrieved and that the reranking process returns the proper chunks. **End-to-end evaluation** is also important.

When building any system, one must consider the **accuracy, latency, and cost targets**. For this reason, it is critical to utilize test datasets and evaluations in order to improve the system.