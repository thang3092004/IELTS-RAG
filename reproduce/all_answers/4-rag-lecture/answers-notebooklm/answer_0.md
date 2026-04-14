The sources highlight the distinction between two primary RAG systems: **text-based RAG** and **vision-based RAG**, particularly in the context of processing documents containing images and tables. Here's a breakdown of their key differences:

**Text-based RAG:**

* **Relies on OCR and Layout Detection:** This system depends on optical character recognition (OCR) to extract text from images and tables. Additionally, it uses layout detection algorithms to understand the document's structure and the relationship between different elements like text blocks, images, and tables.
* **Requires Chunking and Embedding of Text:** The extracted text needs to be divided into smaller chunks. Each chunk is then processed by an embedding model, converting it into a vector representation that captures its semantic meaning. These vector representations are stored in a vector database for retrieval.
* **Separate Processing for Images and Tables:** Images and tables are often treated as separate modalities. Vision models might be employed to generate captions or descriptions for these elements, which are then embedded and added to the vector database alongside text chunks.
* **Challenges with Complex Layouts:** Parsing complex layouts, accurately extracting information from tables, and handling diverse document formats like PDFs can pose significant challenges for text-based RAG systems.

**Vision-based RAG:**

* **Directly Processes Images of Pages:** This system treats each page of the document as an image, eliminating the need for OCR and layout detection.
* **Leverages Vision Language Models:** It utilizes vision language models like ColPali or Quin2 to encode the visual and textual information present in the page images into vector representations.
* **Multi-Vector Representation:** These models employ techniques like ColBERT, generating a multi-vector representation for each page image instead of a single dense embedding vector. This allows for a more nuanced understanding of the page's content and improved retrieval accuracy.
* **Simplified Pipeline and Reduced Complexity:** By directly processing images, vision-based RAG streamlines the pipeline, reducing the number of steps and potential points of error associated with text extraction and separate modality processing.
* **Explainability through Visual Attention:** Vision language models can provide explainability by highlighting the specific areas of the image that contributed to the retrieval or answer generation. This visual attention mechanism enhances transparency and understanding of the model's reasoning process.


In summary, vision-based RAG offers a simpler, more efficient, and potentially more accurate approach to processing documents with rich multimedia content. By directly leveraging the visual understanding capabilities of vision language models, it bypasses the complexities of text extraction and separate modality handling, leading to a more streamlined and robust RAG system.