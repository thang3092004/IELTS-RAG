GraphRAG is a system that combines knowledge graphs with Retrieval Augmented Generation (RAG) to address limitations of current RAG systems. The goal is to improve the accuracy and contextually relevant responses of language models. It works in two phases: indexing and query.

### Indexing Phase

The indexing phase of GraphRAG involves several steps:

* **Chunking**: Similar to traditional RAG, source documents are converted into sub-documents using a chunking strategy.
* **Entity and Relationship Extraction**:  Within each chunk, entities such as people, places, and companies are identified, and the relationships between them are extracted. This information is used to create a knowledge graph.
* **Community Creation**: Based on the knowledge graph, communities are created by detecting entities that are close to each other. The relationships between these communities are then described at different levels, with summaries created for each level.

 ### Query Phase

The query phase involves the following:

* **Query Embedding**: The user's query is embedded using a language model, like in traditional RAG.
* **Community Retrieval**: The embedded query is compared to the summaries of different communities to identify relevant ones.
* **Response Generation**: The model retrieves information from the selected communities, generating partial responses based on the community summaries. If multiple communities are relevant, the partial responses are combined into a single, final response.

 GraphRAG enhances RAG by preserving relationships between entities and providing a more global understanding of the corpus. However, it can be expensive due to the multiple API calls required. While GraphRAG offers potential benefits, traditional RAG may be more suitable for certain applications due to cost considerations.