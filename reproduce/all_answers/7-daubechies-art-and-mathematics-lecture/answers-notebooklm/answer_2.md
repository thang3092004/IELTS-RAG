Circular harmonics played a vital role in the reconstruction of frescoes in the Eremitani Church in Padua, which were destroyed in World War II bombing.  The church had black and white pictures of the frescoes, and the rubble was collected and categorized. The sheer volume of fresco fragments and the lack of context for placement presented a daunting challenge.

**The key property of circular harmonics is their behavior under rotation, making them ideal for this reconstruction task.** Any image on a disk can be represented as a sum of circular harmonics. When a circular harmonic is rotated, the resulting image can be computed quickly and precisely, without needing to recalculate the entire image.

Here's how they used circular harmonics:

*   **Decomposition:** For each fresco fragment, the largest possible circle was inscribed, and the image content within that circle was decomposed into circular harmonics.
*   **Rotation:**  The algorithm considered different rotations of the fragment and calculated the circular harmonic decomposition for each rotation using pre-computed values. This eliminated the need to recalculate for each rotation.
*   **Matching:** These decompositions were compared to a library of circular harmonic decompositions generated from the black and white photos of the frescoes.  The algorithm identified the best matches, usually returning the correct placement.

Volunteers then reviewed the top three matches proposed by the algorithm and selected the correct placement. This combination of mathematical analysis and human input was crucial for the success of the project.