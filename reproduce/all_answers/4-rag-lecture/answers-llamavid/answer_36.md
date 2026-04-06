Late chunking refers to splitting text into chunks and then processing each chunk separately before generating a final response. This approach has both benefits and drawbacks compared to traditional 'sentence level' chunking, which processes text as a whole.

Benefits:
- Late chunking can provide a more nuanced understanding of the input text by focusing on individual chunks. This can lead to more relevant and informative embeddings and contextual information. 
- Late chunking can help reduce the cost of storage and computational resources needed for each chunk, since the context is already encoded in the chunk.

Drawbacks:
- Late chunking requires more text to be processed, which can be costly for very long input texts.
- Late chunking can lose some contextual information if the chunks are too large.

In general, late chunking provides the best of both worlds by preserving context while also being cost efficient. However, it requires more text to be processed, which can be a drawback for very long input texts.