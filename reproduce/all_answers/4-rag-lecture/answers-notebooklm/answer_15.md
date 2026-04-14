The Local GPT Vision system is a vision-based retrieval augmented generation (RAG) system that allows users to chat with their documents securely and locally using open-source models. The system is composed of several key components:

- **User Interface:** This component allows users to upload and index documents (currently supports PDFs and images), create chat sessions, and receive responses along with the document pages from which those responses are derived.
- **Backend:** The backend runs as a Flask app and is responsible for several functions including:
    - Indexing uploaded documents using ColPali and saving them to disk.
    - Managing user chat sessions.
    - Retrieval of relevant images using ColPali based on user questions.
- **ColPali:** This is a vision-based technique that uses a visual encoder to find information in documents. It retrieves the most relevant pages in response to a user's question. It is a simpler solution than traditional RAG, which requires multiple complex steps like OCR, layout detection, chunking, and embedding.
- **Vision Language Models (VLMs):** These models generate responses based on their understanding of both the visual and textual content of the retrieved pages. Local GPT Vision currently supports several VLMs including Quint2 Vision, Gemini, and OpenAI GPT-4. The choice of model and the resolution of the documents impact the quality of the responses.
- **BL Library:** This library makes it simple to work with ColPali.
- **Retrieval Module:** This module uses ColPali to retrieve relevant pages from the indexed documents based on the user's question.

The system leverages the power of VLMs to understand both text and images, eliminating the need for traditional text-based RAG pipelines that require complex pre-processing steps like OCR, layout detection, and text chunking. Local GPT Vision is a two-step process. First, the most relevant pages are retrieved using ColPali. Then, those pages are fed to a VLM along with the original query to generate a final response.