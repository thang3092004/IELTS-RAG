Daubechies illustrates the improvement achieved by multi-tapering with Hermite functions in the synchrosqueezing transform by using the example of **fetal electrocardiogram (ECG) extraction**. 

* She explains that fetal ECG signals are very faint and have a low signal-to-noise ratio (SNR) because they are dominated by the mother’s ECG. 
* Daubechies highlights the problem of **parasitic correlations** introduced by the windowed Fourier transform, even when dealing with white noise. These correlations hinder the clear separation of the fetal heartbeat from the mother's heartbeat. 
* To address this, Daubechies’ team used **multi-tapering with Hermite functions**. Instead of using a single window, they employed multiple windows based on Hermite functions. 
* The results showed a significant improvement in SNR. While some residual parasitic correlations remained, their impact was considerably reduced compared to the rest of the signal. 
* This multi-tapering technique allowed for a much clearer visualization of the fetal heartbeat, showcasing its effectiveness in enhancing signal separation.

Daubechies presents a visual representation of this improvement, comparing the results obtained with and without multi-tapering. The multi-tapered representation exhibits less noise and more defined signal components, making it easier to distinguish the fetal heartbeat.