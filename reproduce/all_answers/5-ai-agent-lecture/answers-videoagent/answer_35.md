Preference alignment is the **third stage** in the process of fine-tuning large language models (LLMs). The purpose of this stage is to **align the model's responses with user preferences**.  It teaches the model to generate outputs that are more desirable or aligned with specific principles or guidelines.

During preference alignment, techniques like **Reinforcement Learning from Human Feedback (RLHF)** and algorithms like **DPO** are used. These methods involve:

* **Collecting human feedback on the model’s responses.**
* **Training a reward model based on the collected feedback.** This reward model learns to score responses based on how well they align with human preferences.
* **Using the reward model to further fine-tune the LLM.** This encourages the model to generate responses that are more likely to receive positive feedback.

Preference alignment is an **optional step**, but many API providers include it in their training pipelines. The result of this stage is often referred to as a **“chat model”**, as it is optimized for interactive conversations and providing responses that are aligned with human expectations and values.