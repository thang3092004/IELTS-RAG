The **Raptor framework**, developed at Stanford University, addresses limitations of traditional RAG systems by introducing two novel retrieval methods: **tree traversal** and **collapsed tree**. These methods enhance the ability to retrieve relevant information from large document sets by utilizing a multi-layered tree structure built upon clustered text chunks.

Let's break down these concepts:

### **Tree Traversal Retrieval**

*   This method utilizes the **hierarchical nature of the Raptor tree**, navigating through different levels of detail to pinpoint the most relevant information for a given query.
*   Imagine it as **following a path through a branching tree**. Starting from the top level, the system examines summaries of clustered text chunks. It then **dives deeper into branches** containing relevant information, ultimately reaching the individual text chunks that are most likely to contain the answer.

### **Collapsed Tree Retrieval**

*   This method simplifies the multi-layered tree structure into a single layer, collapsing the hierarchy while retaining essential information.
*   Think of it as **flattening the tree** while preserving the connections between different levels of information. GPT-4 is then tasked with identifying the most relevant text chunks within this flattened structure, effectively performing a more focused retrieval.
*   Stanford University specifically highlights this method's **effectiveness for multi-hop questioning**, where complex queries are broken down into simpler sub-questions.

**Key advantages of these retrieval methods:**

*   **Holistic understanding:** By clustering and summarizing text chunks, Raptor captures a broader context compared to traditional RAG systems that focus on short, isolated segments.
*   **Multi-level querying:** The tree traversal method allows querying at different granularities, enabling more precise retrieval based on the complexity of the query.
*   **Improved accuracy:** Stanford's research demonstrates that Raptor achieves up to 20% higher accuracy compared to other RAG systems, particularly for tasks requiring a deeper understanding of the document structure.

In summary, the **tree traversal** and **collapsed tree** retrieval methods in Raptor provide a more sophisticated approach to information retrieval, addressing the limitations of traditional RAG systems in handling complex queries and capturing a comprehensive understanding of document context.