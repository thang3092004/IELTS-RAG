There are three popular techniques for supervised fine-tuning of large language models (LLMs): full fine-tuning, LoRA, and QLoRa.

### Full Fine-Tuning

In **full fine-tuning**, the entire original model's weights are updated with the instruction fine-tuned dataset. Full fine-tuning offers the **best performance**, depending on the size and quality of the dataset. However, this approach demands **high GPU VRAM** due to the extensive weight updates.

### LoRA (Low-Rank Adaptation)

**LoRA** avoids direct weight updates by adding external adapters to the original model. The number of parameters in these adapters can be controlled, impacting performance and resource requirements. **Weight updates for LoRA adapters are typically performed in 16-bit precision**, which is faster but still computationally expensive. Later, these adapters can be merged with the original model weights. LoRA offers **faster training** than full fine-tuning but remains **costly** due to the 16-bit precision operations.

### QLoRa (Quantized Low-Rank Adaptation)

**QLoRa** builds upon the LoRA concept but optimizes for efficiency. Like LoRA, QLoRA utilizes external adapters, but the **weight updates are performed in 4-bit precision**. Additionally, **the original model weights are also kept in 4-bit quantization**. This approach **significantly reduces VRAM requirements**, enabling fine-tuning on consumer-grade GPUs. However, the **performance may not be as high** as LoRA or full fine-tuning due to the lower precision.