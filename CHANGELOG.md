# Changelog

## Next version

### ✨ Improved

* `mech move --home` has been renamed to `--center`.
* Moving all three collimator motors at once to an absolute position is no longer allowed.
* Additional safety checks before sending any move command to the collimator motors.
* `SpecMechReply.sentence` has been removed since different replies for the same command can have difference sentences. The sentence is stored as the first value in the reply on each `SpecMechReply.data` (the `S[0-9]` prefix is removed).


## 0.1.0 - June 11, 2022

### 🚀 New

* Initial version of `yao`.
* [#1](https://github.com/sdss/yao/pull/1) Initial implementation of the specMech controller based on [specActor](https://github.com/aidancgray/specActor).
