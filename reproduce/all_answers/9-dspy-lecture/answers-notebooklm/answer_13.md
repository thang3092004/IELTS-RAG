DSP leverages in-context learning by providing the language model with a few-shot learning approach. This means the LLM is given a small set of examples that demonstrate the desired behavior for a particular task. The LLM can then learn to perform the task based on these examples without requiring retraining.

**The “demonstrate” stage is where in-context learning is used.** In this stage, the LLM is provided with a prompt that includes a few examples of the task. These examples show the desired input and output, allowing the LLM to learn the task by example.

*   **The examples provided to the LLM are called demonstrations**. A demonstration is a specifically prepared training example illustrating a specific desired behavior from the LLM.

*   The LLM can then use these demonstrations to generate new synthetic training data on the fly that is specific to the knowledge domain and the task at hand. This allows the LLM to continuously learn and adapt, improving its accuracy and efficiency over time.


**This approach avoids retraining the LLM**. **Instead, it adapts the model to the specific task using in-context learning within the prompt's context length**. This means that the LLM's weight tensors remain fixed, but it can still generate relevant responses by using the provided demonstrations.  This approach is referred to as **retrieval augmented in-context learning (RAICL)**.