# Changelog

## Next version

### 🏷️ Changed

* Disable the Archon fan.


## 1.3.3 - August 27, 2024

### ✨ Improved

* Log specMech commands and replies to disk.
* Set specMech time periodically.

### ⚙️ Engineering

* Format code using ruff and update workflows.


## 1.3.2 - May 29, 2024

### ✨ Improved

* Bump `archon` to 0.13.5.


## 1.3.1 - February 27, 2024

### ✨ Improved

* Bump `archon` to 0.13.4.

### 🔧 Fixed

* Fix temperature alerts not being raised if the controller was not available.


## 1.3.0 - December 22, 2023

### ✨ Improved

* Bump `archon` to 0.13.2.


## 1.3.0b2 - December 17, 2023

### 🔧 Fixed

* [#14](https://github.com/sdss/yao/pull/14) Support `archon` 0.13.x.


## 1.3.0b1 - December 15, 2023

### ⚙️ Engineering

* [#12](https://github.com/sdss/yao/pull/12) Deprecate 3.9, support 3.12. Lint using `ruff`. Update workflows.
* [#13](https://github.com/sdss/yao/pull/13) Updates to FFS and lamps headers.

### 🔧 Fixed

* Increase timeout for specMech pneumatic issues.


## 1.2.1 - July 26, 2023

### ✨ Improved

* Check if shutter times out while opening/closing. If the shutter fails closing, the exposure is read anyway.
* Check if specMech is responding on each `mech`` actor command.


## 1.2.0 - April 26, 2023

### ✨ Improved

* Use `BOSS_extra_purge_erase_v8.acf` which mimics the voltages used at APO for b2 (e2v). This seems to solve the "puddles" seen around the serial register and may improve the settle time after a power cycle.


## 1.1.0 - April 13, 2023

### 🚀 New

* [#2](https://github.com/sdss/yao/pull/2) Add alerts for LN2 and CCD temperature and actor heartbeat.

### ✨ Improved

* Use new ACF file with e-purge, erase, and improvements to horizontal transfer.
* Change flushing to not binned.
* Upgraded to use `sdss-archon>=0.9.0`.
* The collecting of actor information (lamps, specMech, etc.) now happens during the exposure instead of after readout completes.
* Create checksum files using `sha1sum`.

### 🏷️ Change

* Set b2 temperature to -98 degC.


## 1.0.0 - October 19, 2022

### 🚀 New

* First stable version tested at LCO.
* Added `MechController.pneumatic_status()` method.

### ✨ Improved

* `mech move --home` has been renamed to `--center`.
* Moving all three collimator motors at once to an absolute position is no longer allowed.
* Additional safety checks before sending any move command to the collimator motors.
* `SpecMechReply.sentence` has been removed since different replies for the same command can have difference sentences. The sentence is stored as the first value in the reply on each `SpecMechReply.data` (the `S[0-9]` prefix is removed).
* Added multiple new header keywords (LCO TCC, specMech, etc.)

### 🏷️ Changed

* Rename `fan_volts` -> `power_supply_volts`.

### 🔧 Fixed

* Fixed several bugs and confirmed that `yao hartmann` works as expected.


## 0.1.0 - June 11, 2022

### 🚀 New

* Initial version of `yao`.
* [#1](https://github.com/sdss/yao/pull/1) Initial implementation of the specMech controller based on [specActor](https://github.com/aidancgray/specActor).
