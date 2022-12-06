# ACF versions

## BOSS_extra.acf

Very initial version of the BOSS timing script with modifications to work with the archon Python package. Does not include erase or e-purge.

## BOSS_extra_purge_erase_v2.acf

First version with erase and e-purge, although the voltages are different from following versions. e-purge happens during each exposure.

## BOSS_extra_purge_erase_v3.acf

New versions of erase and e-purge. The e-purge is built as an independent stage.

## BOSS_extra_purge_erase_v4.acf

Same as v3 but changes the serial swings to 0 - +3V during integration and idle, and sets the VDD to 0V during those phases. This removes the "puddles" coming out of the serial registers.

The default for autoflushing is not binning when shifting lines. The e-purge routine is followed by a 1-x binned flushing, but that's done in yao.

There's still a gradient along the serial direction with pixels read early having a slightly higher signal (~2 ADU).

## BOSS_extra_purge_erase_v5.acf

Adds a `DummyPixel` routine that runs after each vertical shift and reads a number of `DummyPixels` but only changing the SW and reset voltages (no serial clocking). This seems to deal to some degree with some bias coming out of the substrate after each vertical shift.
