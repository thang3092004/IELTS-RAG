When using SuperDecisions to implement a ratings model, defining and using rating scales is a crucial step. Here's a breakdown of the process:

**Defining Rating Scales**

*   **Select the Criterion:** Begin by choosing the criterion for which you want to define a rating scale. For example, if you're evaluating cars, you might start with "Prestige".
*   **Create or Load a Scale:** SuperDecisions offers flexibility in defining scales:

    *   **Load an Existing Scale:** Select from pre-defined scales saved as .RCP files. These cover common evaluation criteria like "Excellent to Poor."
    *   **Create a Custom Scale:** Tailor scales to your specific needs. This is beneficial when standard scales don't adequately represent your criteria. For instance, when defining a price scale, you can create custom ranges like "$10,000-$15,000," "$16,000-$21,000," and so on.
*   **Define Scale Values:**

    *   **Pairwise Comparisons:** For custom scales, establish the relative importance of scale items through pairwise comparisons. This quantifies the relationships between items like "Good" versus "Average."
    *   **Direct Entry:** If you have precise numerical values, enter them directly. This works well for objective criteria like "Miles per Gallon".
*   **Save the Scale:** Once defined, save the scale for reuse in the current or future models.

**Utilizing Rating Scales**

*   **Evaluate Alternatives:** Use the defined scales to rate each alternative against the chosen criteria. Remember, you're comparing alternatives to an ideal, not against each other.
*   **View Scale Representations:** SuperDecisions offers different ways to view scale items:

    *   **Category Names:** Displays only the names of scale items (e.g., "Excellent," "Good").
    *   **Priorities:** Shows the numerical values associated with each scale item.
    *   **Both:** Presents both the names and numerical values for a comprehensive view.
*   **Show/Hide Priorities:** Control the visibility of numerical priorities and total values within the rating table.
*   **Synthesize Results:** After rating alternatives, synthesize the model to obtain results. This reveals the ranking of alternatives based on your ratings.

**Key Considerations**

*   **Expertise:** Ratings models rely on your understanding of the subject matter. Ensure you have sufficient expertise to make informed judgments.
*   **Objectivity:** Avoid comparing alternatives directly during rating. Focus on evaluating each alternative against the ideal defined by your scale.
*   **Consistency:** Pay attention to consistency ratios during pairwise comparisons to ensure the reliability of your scale values.
*   **Model Conversion:** You can convert an existing AHP model to a ratings model in SuperDecisions, simplifying evaluations when dealing with many alternatives.

By meticulously defining and utilizing rating scales, you can leverage SuperDecisions to effectively implement ratings models and make well-informed decisions.