To convert an Analytic Hierarchy Process (AHP) model into an Analytic Network Process (ANP) model in the Super Decisions software, there are several key steps involved. First, it's important to recognize the structural differences between AHP and ANP models. In an AHP model, there is a distinct goal cluster at the top that connects to criteria, which in turn link to alternatives. In contrast, an ANP model does not have a goal cluster and can contain multiple clusters that encapsulate criteria and alternatives.

### Steps for Conversion from AHP to ANP

1. **Open the Existing AHP Model**: Start by accessing the AHP model you wish to convert. This is achieved by opening a sample model through the Help menu in Super Decisions.

2. **Identify and Remove the Goal Node**: Since ANP does not utilize a goal node, the first step in conversion is to remove this element from your model. You will then have clusters for criteria and alternatives, allowing for a more interconnected structure.

3. **Create Alternative Clusters**: In an ANP model, you can have multiple clusters, meaning you should consider reorganizing and potentially creating new clusters for various criteria if the existing model dictates such a structure.

4. **Establish Connections Between Criteria and Alternatives**: Unlike AHP, where connections are made in a linear fashion from the goal to criteria and then to alternatives, in ANP, it is essential to create connections that allow for mutual influences among clusters. This involves connecting each criterion with every alternative it influences or is influenced by.

5. **Add Judgment Inputs**: An essential aspect of ANP models is that they require additional judgments compared to AHP. You will need to assess the relative importance of each criterion considering every alternative, essentially comparing criteria with respect to each of the alternatives. This may involve entering pairwise comparisons or relative ratings across clusters that were not previously required in the AHP structure.

### Additional Judgments Required

The main additional judgments needed when converting an AHP model to an ANP model include:

- **Importance of Criteria Relative to Alternatives**: You will need to evaluate how important each criterion is for each alternative. This step was less emphasized in AHP, where comparisons were primarily from alternatives back to criteria.
  
- **Interdependencies Among Clusters**: The ANP model captures the complex relationships or dependencies between different criteria. Judgments should be made regarding how the criteria might affect one another and how they relate to various alternatives, reflecting the dynamic nature of decision-making situations.

### Summary

In summary, converting an AHP model to an ANP model in Super Decisions involves structural modifications, removal of the goal node, establishment of new connections, and additional judgments that evaluate the interactions and relative importance of criteria regarding alternatives. These steps facilitate a deeper and more pragmatic exploration of decision-making processes, aligning with the greater flexibility and complexity that ANP offers compared to AHP.