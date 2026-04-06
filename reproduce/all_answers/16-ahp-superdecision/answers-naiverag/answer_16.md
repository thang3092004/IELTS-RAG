## Synthesizing an AHP Model in SuperDecisions

The synthesizing process in an Analytic Hierarchy Process (AHP) model, specifically using the SuperDecisions software, is critical for obtaining global priorities for alternatives. This involves multiple steps that ensure a comprehensive evaluation of options against defined criteria. Below is an overview of the process.

### 1. **Model Structure Setup**

The first step in synthesizing an AHP model is to establish a clear structure within SuperDecisions. The model typically consists of three hierarchical levels:

- **Goal**: The ultimate objective (e.g., selecting the best alternative).
- **Criteria**: Important factors or attributes that influence the decision (e.g., cost, comfort, efficiency).
- **Alternatives**: The choices being evaluated (e.g., specific car models).

Each criterion must be associated with the alternatives, allowing for pairwise comparisons at each level.

### 2. **Input Judgments**

Once the structure is set up, users input judgments through pairwise comparisons. This means evaluating how each alternative performs against each criterion. Judgments are usually entered on a scale (commonly from 1 to 9), where each number represents a degree of preference between a pair of items. For example, a judgment of 9 indicates a strong preference for one alternative over another.

### 3. **Computing Local Priorities**

After the judgments are entered, SuperDecisions computes **local priorities** for each criterion. This essentially transforms the comparative judgments into numerical values that indicate the relative importance or priority level of each alternative concerning the criteria. 

The local priorities are derived directly from the pairwise comparisons through matrix calculations, which normalize the input values to reflect their relative weightings accurately.

### 4. **Synthesis of Global Priorities**

With the local priority values calculated, the next step is to synthesize them to derive the **global priorities**. This is done through the following sub-steps:

- **Constructing a Supermatrix**: The system may create a supermatrix that integrates the local priorities of all criteria and their corresponding alternatives, maintaining the hierarchical relationships established earlier.
  
- **Calculating Global Values**: The supermatrix is manipulated to calculate global priorities. These values represent the overall desirability of each alternative when all criteria are taken into account. This involves aggregating the local priorities while considering the importance of each criterion.

### 5. **Consistency Check**

A crucial aspect of the AHP process is the consistency of the judgments provided. SuperDecisions checks the consistency ratio to ensure that the inputs are rational and reasonable. A consistency ratio below a certain threshold (often 0.1) signifies acceptable consistency, confirming that the judgments are logically aligned and defensible.

### 6. **Interpreting Results**

Finally, once the synthesis is complete, the global priorities for each alternative can be interpreted. The results indicate which alternative is preferred overall based on the collective evaluation across criteria. This data can serve as a decisive factor in decision-making processes.

### Conclusion

The synthesis of an AHP model in SuperDecisions is a structured and systematic approach that allows decision-makers to derive meaningful insights from structured comparisons. By effectively navigating through model setup, judgment input, local and global priority computation, and consistency evaluation, users can ensure a robust decision-making framework, leading to well-informed choices among alternatives. This process not only elucidates preferences for specific options but also enhances understanding of the impact of various criteria on the overall decision.