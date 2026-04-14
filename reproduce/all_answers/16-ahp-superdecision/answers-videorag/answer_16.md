The process of synthesizing an Analytic Hierarchy Process (AHP) model in SuperDecisions involves several crucial steps aimed at deriving global priorities for decision alternatives based on subjective assessments of various criteria. Below is a detailed explanation of the process, organized into distinct phases:

### 1. **Model Structure Setup**

The first step in synthesizing an AHP model is to establish a clear structured hierarchy. This involves defining the goal of the decision-making process at the top level, which is connected to the criteria that will inform the decision. Below the criteria, alternatives are listed that represent the options available for selection.

- **Hierarchical Framework:** An AHP model typically portrays a hierarchical structure with three levels:
  - **Level 1:** The overall goal (e.g., selecting the best alternative).
  - **Level 2:** Criteria impacting the decision (e.g., price, quality, service).
  - **Level 3:** Alternatives being evaluated (e.g., different product models).

### 2. **Pairwise Comparisons**

Once the hierarchical structure is established, the next step is to perform pairwise comparisons. This involves comparing the elements within each level against one another to determine their relative importance.

- **Judgments:** In SuperDecisions, the user inputs judgments in a pairwise comparison matrix, assessing how much more one element is preferred over another concerning a particular criterion on a scale (typically from 1 to 9).
- **Reciprocal Values:** If element A is judged as being three times more important than element B, that judgment is entered, and the reciprocal (1/3) is applied for the inverse comparison.

### 3. **Computing Priorities**

After the pairwise comparisons have been entered for all criteria and alternatives, SuperDecisions synthesizes the information to compute the local priorities for the alternatives based on each criterion.

- **Priority Vectors:** The software generates a priority vector for each criterion based on the pairwise comparison matrix. This vector represents the relative importance of alternatives under that criterion.
- **Normalization:** The values in the priority vectors are normalized to ensure they sum to 1, creating a clear ranking among options.

### 4. **Synthesis of Global Priorities**

The final step involves synthesizing the local priorities obtained from each criterion into global priorities. This step combines the local priority values with the weights assigned to each criterion to determine the overall priority of each alternative.

- **Weighted Sum Model:** SuperDecisions employs a weighted sum approach, calculating a global priority for each alternative by summing the products of the local priorities and the weights (importance) of their corresponding criteria:
  \[
  \text{Global Priority} = \sum (\text{Local Priority}_{i} \times \text{Weight}_{i})
  \]
- **Final Ranking:** The alternatives are then ranked according to their global priorities, allowing decision-makers to identify the option that best aligns with the established criteria and their importance.

### 5. **Sensitivity Analysis (Optional)**

Often, after obtaining the global priorities, a sensitivity analysis is conducted. This analysis helps understand how changes in the weights of criteria influence the final outcomes, ensuring the robustness of the decisions made.

- **Dynamic Sensitivity:** SuperDecisions can show how changes in the importance of criteria affect the rankings of alternatives, allowing for a more informed decision-making approach.

### Conclusion

By following these structured steps in SuperDecisions, users can effectively create an AHP model that not only aids in synthesizing priorities for decision alternatives but also provides insights into the sensitivity of those decisions to variations in criteria weights. This systematic approach ensures that decision-making is aligned with the preferences of stakeholders involved in the process, enhancing the overall effectiveness of the analysis.