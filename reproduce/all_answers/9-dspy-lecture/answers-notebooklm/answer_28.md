The retrieval of a large number of text passages is crucial for accurate RAG performance, especially in specialized domains or when dealing with new knowledge, because **current retrieval models may not identify the most relevant passages within a smaller set of retrieved documents**. The sources explain that this is due to several limitations with current RAG systems, including:

* **Limited Holistic Understanding**: Most RAG systems retrieve only short chunks of text, hindering their ability to grasp the overall document context. This is particularly problematic when dealing with complex reasoning or new knowledge that spans multiple pages or documents.

* **New Knowledge Challenges**: When dealing with new research, the semantic correlations may not be adequately represented within the existing retrieval model, even after fine-tuning. This means that relevant passages containing new knowledge may be ranked lower in relevance, requiring the retrieval of a larger number of passages to ensure inclusion.

* **Information Overload and Non-Informative Text**:  The vast amount of available information online, including a significant portion of irrelevant or non-informative text, makes it difficult for retrieval models to consistently pinpoint the truly valuable passages. Retrieving a larger number of passages increases the chances of capturing the crucial information needed for accurate answers.

These limitations highlight the importance of retrieving a sufficient number of text passages. Relying on a small set of retrieved documents might mean that **the crucial information needed for an accurate answer is ranked lower in relevance and is not included**, as demonstrated by the official RAGatouille notebook, where the desired document paragraph was ranked 14th. This issue is amplified when dealing with specialized domains or new knowledge, where relevant passages are more likely to be buried deeper in the search results. 

The sources present several approaches to address these challenges:

* **Corrective RAG Systems**: Google Research proposes a system that evaluates the relevance of retrieved passages before passing them to the LLM. This helps filter out irrelevant information and ensures that only the most pertinent passages are used for answer generation.

* **Recursive Abstractive Processing (Raptor)**: Stanford University introduces a method that constructs a hierarchical tree structure of the retrieved corpus, allowing for a more comprehensive understanding of the document context. This approach is particularly effective for multi-hop questioning, where reasoning across multiple documents is necessary.

* **Increased Retrieval Depth**: Recognizing the limitations of relying on a small set of retrieved documents, experts suggest increasing the number of retrieved passages, especially when dealing with specialized domains or new knowledge.

By addressing these limitations and adopting new techniques, RAG systems can be improved to achieve greater accuracy, especially in specialized domains or when dealing with new knowledge.