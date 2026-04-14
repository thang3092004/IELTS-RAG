The limitations of using vision-language models like Quin-2 for local multimodal RAG implementations include:

1. **Resource Requirements**: 
   - **Computational Power**: Vision-language models often require significant computational resources, including high-performance GPUs, to process and analyze visual and textual data efficiently.
   - **Memory Usage**: These models can be memory-intensive, especially when dealing with high-resolution images or long documents, which can be a constraint for local implementations.
   - **Storage Needs**: Storing large models and datasets locally can be challenging due to their size.

2. **Model Performance on Complex Documents**:
   - **Understanding Context**: Vision-language models may struggle with understanding complex documents that require deep contextual understanding or domain-specific knowledge.
   - **Multimodal Integration**: Effectively integrating and reasoning over both visual and textual information can be challenging, especially when the information is abstract or not directly related.
   - **Generalization**: These models might not generalize well to unseen or highly complex document types without fine-tuning or additional training data.

Overall, while vision-language models like Quin-2 offer powerful capabilities, their resource demands and potential performance limitations on complex documents can pose challenges for local multimodal RAG implementations.