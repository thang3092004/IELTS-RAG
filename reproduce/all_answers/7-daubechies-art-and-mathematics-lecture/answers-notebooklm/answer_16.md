Daubechies's team developed an algorithm to address the challenge of 'cradle' interference in X-ray images of panel paintings. This algorithm **automatically identifies and removes the 'cradle' wood grain while preserving the wood grain of the original panel**.

**Cradle interference** occurs when X-rays penetrate the panel painting and capture the image of the supporting lattice structure ('cradle') on the back, obscuring the details of the artwork itself. This lattice structure, made of hardwood, was typically added by conservators to stabilize the thinned-down panels, preventing warping.

Prior to the development of this algorithm, conservators spent countless hours manually removing cradle marks using Photoshop before publishing X-ray images of the artwork.

**Daubechies's team's approach:**

* Utilized image decomposition techniques to separate wood grain from other features.
* Employed curvelets to identify and extract long, continuous strands of wood grain.
* Used Bayesian methods to differentiate between the two types of wood grain (original panel and cradle) and selectively remove the cradle wood grain.

**Impact of this work:**

* **The algorithm outperformed manual Photoshop editing by professional art conservators in removing cradle interference**.
* The team received a grant to develop open-source software called **Project Platypus**, which makes the algorithm accessible to conservators worldwide.
* **Project Platypus** includes a gallery showcasing numerous before-and-after images of paintings, demonstrating the effectiveness of the algorithm.
* A ground truth test, using X-rays of a painting before and after physical cradle removal, helped validate the algorithm and led to its publication.

This innovation in image analysis has significantly benefited the field of art conservation by **improving the clarity of X-ray images and enabling more detailed study of the artwork's brushwork and underlying structure.