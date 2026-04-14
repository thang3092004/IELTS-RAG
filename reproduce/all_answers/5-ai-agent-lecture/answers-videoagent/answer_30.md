The three main supervised fine-tuning techniques are:

1. **Feature Extraction**: This involves using a pre-trained model as a fixed feature extractor. The performance implication is that it is computationally efficient and works well when the new task is similar to the original task the model was trained on.

2. **Fine-Tuning**: This technique involves unfreezing some of the top layers of the pre-trained model and jointly training the last layers with the new classifier. The performance implication is that it can lead to better performance on the new task, especially if the new task is somewhat different from the original task, but it requires more computational resources.

3. **Full Model Fine-Tuning**: This involves unfreezing the entire model and retraining it on the new dataset. The performance implication is that it can potentially lead to the best performance on the new task, especially if the new task is very different from the original task, but it is computationally expensive and requires a large amount of data to avoid overfitting.