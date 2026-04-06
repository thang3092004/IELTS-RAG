Identifying the correct rotation of fresco fragments presents a significant mathematical challenge because **simply comparing the numerical pixel values of two images doesn't work when one is rotated**. This is because even if two images are identical except for rotation, their corresponding pixel grids will have completely different numerical representations.

To overcome this obstacle, Massimo Fornasier used a mathematical tool called **circular harmonics**. Circular harmonics are special functions that have well-defined behavior under rotation, meaning they transform predictably when rotated.

Here's how circular harmonics helped solve the fresco puzzle:

* **Decomposition:** Any image on a disk can be broken down into a sum of circular harmonics, much like a musical chord is composed of different notes. Each circular harmonic component contributes a specific pattern to the overall image.
* **Rotation:** When a circular harmonic is rotated, its numerical representation is simply multiplied by a known factor determined by the rotation angle. This means that **instead of recalculating the entire image for each possible rotation, you only need to adjust the coefficients of the circular harmonic components**.
* **Matching:** By representing both the fresco fragments and the target black-and-white images using circular harmonics, researchers could quickly compare them across all possible rotations. This dramatically reduced computation time, making the project feasible.
* **Speed and Accuracy:** The use of circular harmonics enabled the development of a fast algorithm that could identify the likely positions and rotations of thousands of fresco fragments, drastically accelerating the reconstruction process. While human judgment was still needed to make the final selection, the algorithm significantly narrowed down the possibilities.

In summary, circular harmonics provided a computationally efficient way to represent and compare images regardless of their rotation, overcoming a major obstacle in the fresco reconstruction project. This mathematical insight was crucial to the success of digitally piecing together the fragmented frescoes.