The Local GPT Vision system consists of three main components: 1) the vision-based retrieval, 2) the late chunking, and 3) the agentic RAG pipeline. 

1) Vision-based retrieval: The vision-based retrieval uses a vision language model to retrieve information from the input document. 

2) Late chunking: Late chunking splits the input document into chunks and embeds each chunk separately. This late chunking approach preserves contextual information within the chunks. 

3) Agentic RAG pipeline: The agentic RAG pipeline combines the retrieved context from the vision-based retrieval and the late chunked embeddings to generate a final response.

The vision-based retrieval and late chunking allow the system to process the input document efficiently and preserve contextual information within the chunks. The agentic RAG pipeline then uses the retrieved context and late chunked embeddings to generate a final response.