# BOSS SP2 Installation Notes

A number of lessons where (re)learned during the move and installation of BOSS SP2 at LCO. This document summarises some of that information so that it is not (immediately) forgotten.

## Historical background

As part of SDSS-V, it was decided to move one of the BOSS spectrographs (sp2) to Las Campanas. Taking advantage of this opportunity, two major changes were made to the spectrograph:

1. The mechanical components and associated electronics (specMech) were replaced with modern components and a new controller. The new specMech documentation can be found [here](./static/specMech%20Communications%20Guide.pdf).
2. The CCD controller was replaced with an STA Archon controller. The clock drivers and preamplifier were not replaced and they are instead managed by the Archon.

The Archon provides 8 general use digital IO in the HeaterX module and another 8 in the LVXBias module. These DIO allow to externally control the serial (HeaterX) and parallel (LVXBias) clocks. The voltages for these signals are defined in the LVXBias module. Modules 1, 2, 4, and 6 control the LBNL r2 chip. Modules 7, 9, 11, 12 control the e2v b2 chip.

A limitation of using external clock drivers is that voltages can not be ramped up or down in a controlled way, and each timing state can only change one voltage at a time by overriding the initial/default voltage. The Archon clock unit is 10 ns.

The voltage for each signal is set in the LVXBias module (high, fixed voltages are set in the XVBias). To change the value of a signal one must create a new timing state and override the desired voltage. The settling time when a voltage changes is 10 ms and it is not possible to control the slew speed.

## Installation at LCO

SP2 was installed at the du Pont telescope in August 2022. An issue with the air purge system, and a problem with b2 hold time required additional work in September.

Initially, a light leak was identified in b2 images, caused by an open screw hole in b2 and a transparent tube inlet. Both problems were solved by applying black tape to cover the hole and tube.
