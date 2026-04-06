## Converting an AHP Model to an ANP Model in Super Decisions

The conversion of an Analytic Hierarchy Process (AHP) model to an Analytic Network Process (ANP) model within the Super Decisions software involves several systematic steps tailored to accommodate the differences in the underlying structures of these models. While both methodologies serve to facilitate complex decision-making processes, ANP allows for the consideration of interdependencies among decision elements, which is a distinction from the hierarchical nature of AHP.

### Step-by-step Conversion Process

1. **Open Existing AHP Model**: Begin by loading the AHP model you wish to convert. You can do this by accessing sample models from the Help menu in the Super Decisions interface.

2. **Identifying Clusters**: In the ANP model structure, it is crucial to understand that clusters are employed to group related criteria and alternatives. Unlike AHP, which focuses on a singular goal node, ANP can have multiple clusters, each representing different criteria.

3. **Remove the Goal Node**: Since ANP models do not utilize a distinct goal cluster, the first step is to remove the goal node from your AHP model. This adaptation opens the way for a looser structure, allowing multiple influence paths, unlike the strict hierarchy in AHP.

4. **Establishing Connections**: The primary task in creating an ANP model is establishing the connections between criteria and alternatives. Each criterion in your model should be connected to relevant alternatives. This reciprocal relationship forms the backbone of the ANP framework, emphasizing mutual influence rather than a unidirectional hierarchy.

5. **Defining Judgments**: Once the connections are established, the next necessary step involves making additional judgments to quantify the strength of interdependencies. This could involve pairwise comparisons between criteria and alternatives just like in AHP, but additionally requires assessing how each alternative influences the criteria and vice versa.

### Additional Judgments Required

To effectively operationalize an ANP model, users must make several additional judgments as compared to those required in an AHP framework:

- **Judgments on Interdependencies**: Users need to assess the degree of influence each criterion has on the alternatives and the influence of the alternatives on the criteria. This necessitates an understanding of the reciprocal nature of these relationships.

- **Evaluating Multiple Factors**: As ANP allows for multiple cluster interactions, users must make judgments on how criteria within different clusters influence one another.

- **Revisiting Pairwise Comparisons**: While AHP utilizes pairwise comparisons of factors for prioritization, in ANP, these comparisons should reflect the interconnectedness of criteria and alternatives. Evaluating this interconnectivity will require more detailed and nuanced assessments than in a traditional hierarchical model.

### Conclusion

Transitioning from an AHP to an ANP model in Super Decisions entails a structured adjustment to accommodate a more complex decision framework inherent to ANP. This transition not only involves the removal of the goal node but also emphasizes the need for additional judgments regarding influence relationships among decision elements. By recognizing these differences and implementing the corresponding adjustments, users can effectively leverage ANP to facilitate more comprehensive decision-making processes reflective of real-world complexities.