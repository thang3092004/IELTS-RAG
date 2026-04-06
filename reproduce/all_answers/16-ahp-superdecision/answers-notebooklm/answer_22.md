The process of synthesizing a model with sub-criteria in SuperDecisions is similar to synthesizing a model without sub-criteria, but with an additional step of calculating the weighted priorities of the sub-criteria. 

**In both cases, the synthesis process involves calculating the global priorities of the alternatives based on the local priorities of the alternatives with respect to each criterion and the weights of the criteria.**

**When a model includes sub-criteria, the software first calculates the local priorities of the alternatives with respect to each sub-criterion.** Then, it calculates the weighted priorities of the sub-criteria with respect to their parent criterion. Finally, the software uses these weighted priorities to calculate the global priorities of the alternatives.

Here is a step-by-step explanation of the synthesis process with sub-criteria:

*   **Pairwise comparisons of sub-criteria:** The sub-criteria are compared pairwise with respect to their parent criterion to determine their relative importance.
*   **Calculation of sub-criteria weights:** The software calculates the weights of the sub-criteria based on the pairwise comparisons.
*   **Pairwise comparisons of alternatives with respect to sub-criteria:** The alternatives are compared pairwise with respect to each sub-criterion to determine their local priorities.
*   **Calculation of weighted local priorities:** The local priorities of the alternatives with respect to each sub-criterion are multiplied by the weight of the corresponding sub-criterion.
*   **Summation of weighted local priorities:** The weighted local priorities of the alternatives for all sub-criteria under a given criterion are summed to obtain the overall local priority of each alternative with respect to that criterion.
*   **Calculation of global priorities:** The software uses the overall local priorities of the alternatives with respect to each criterion and the weights of the criteria to calculate the global priorities of the alternatives.

**In contrast, when a model does not have sub-criteria, the software directly compares the alternatives with respect to each criterion and then uses the local priorities and criteria weights to calculate the global priorities.**

Essentially, **the presence of sub-criteria adds an extra layer of complexity to the synthesis process by requiring the calculation of weighted priorities for the sub-criteria before calculating the global priorities of the alternatives.**