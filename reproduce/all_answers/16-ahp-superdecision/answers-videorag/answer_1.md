Converting an Analytic Hierarchy Process (AHP) model into an Analytic Network Process (ANP) model in SuperDecisions involves several specific steps along with the need for additional judgments. Here is a structured approach to accomplish this.

### Steps to Convert AHP to ANP in SuperDecisions

1. **Open Existing AHP Model**: Begin by launching SuperDecisions and opening the AHP model that you want to convert. You can typically find the model under the Help menu’s sample models.

2. **Modify the Network Structure**:
   * In an AHP model, there exists a "Goal" node at the top of the hierarchy. In contrast, ANP models do not require a goal node. The first step in the conversion is to **remove the goal node** from the existing AHP model.
   * An ANP model comprises *criteria clusters* and *alternatives clusters* without a single overarching goal.

3. **Add Criteria Clusters**: ANP allows for multiple criteria clusters, unlike AHP, which only uses one. You can create additional criteria clusters as necessary, ensuring these clusters can include related criteria.

4. **Create Alternative Clusters**: Similar to criteria, you will also define clusters for alternatives if they are not already established. This step creates a more interconnected network of relationships among the alternatives and criteria.

5. **Add Connections**: Unlike AHP, where connections are primarily from criteria to alternatives, ANP models require connections between alternatives and criteria, which allow direct comparisons of the alternatives with respect to each criterion. It is critical to set these connections up properly to reflect the network structure.

### Additional Judgments Required

Following the conversion of the AHP model to an ANP format, several additional judgments are necessary:

- **Interrelationship Judgments**: Since ANP includes a more complex network, you will need to evaluate how different criteria relate to one another and how they affect the alternatives. For example, judges may need to compare how important each criterion is in the context of each alternative.

- **Direct Pairwise Comparisons for Alternatives**: ANP also requires pairwise comparisons of how alternatives perform against each criterion, in addition to how different criteria affect each other. 

- **Feedback Loops**: Often, ANP models need to account for feedback loops between criteria and alternatives that might not have been evident in the simpler AHP model. This requires careful judgment on the interdependencies that exist among the criteria and alternatives.

### Conclusion

Conversion from AHP to ANP in SuperDecisions requires a meticulous modification of your model structure along with additional judgments regarding the interconnections and comparative evaluation of criteria and alternatives. This complex interlinking enables a more dynamic decision-making framework, capturing the interdependencies in the alternatives under consideration. By following these steps, you will be able to transition effectively to the ANP model, allowing for enhanced decision-making through greater flexibility and richness in modeling relationships between attributes.