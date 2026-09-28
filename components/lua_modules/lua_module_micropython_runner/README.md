# MicroPython UI runner

`require('micropython_runner')` provides start(), stop(), jobs(), returning (ok, message).
start() launches only /sdcard/labplus/generated_runner.py, in exclusive group ui_program,
with a 60 second limit and without replacing an existing job. Select/review code first.
It runs asynchronously so the shared display/audio Lua job continues.
stop() requests cooperative cancellation. Wait for terminal job state before another run.
validate('/sdcard/programs/example.py') returns (ok, message, busy). It compiles the actual
MicroPython source without executing it. If busy, defer validation until the single VM is free.
Syntax success is not a guarantee of correct program behavior or hardware API availability.

`start(true)` is reserved for the user's explicitly selected boot program: it disables
the 60 second deadline, while preserving VM exclusivity, bounded heap and cooperative
stop. Do not use it for arbitrary model-generated execution without user selection.
