from pathlib import Path
from lupa import LuaRuntime
root = Path(__file__).resolve().parents[1]
lua = LuaRuntime(unpack_returned_tuples=True)
lua.globals().VOICE_PATH = str(root / 'sdcard/labplus/voice.lua')
lua.execute((root / 'tests/voice_state.lua').read_text())
for path in (root / 'sdcard').rglob('*.lua'):
    lua.execute('assert(load(...))', path.read_text())
print('PASS: Lua syntax for deployment scripts')
compile((root/'sdcard/esp_claw.py').read_text(), 'esp_claw.py', 'exec')
print('PASS: Python syntax')

lua = LuaRuntime(unpack_returned_tuples=True)
lua.globals().SHELL_PATH = str(root / 'sdcard/labplus/shell.lua')
lua.globals().LIMITS_PATH = str(root / 'sdcard/labplus/limits.lua')
lua.globals().UI_PATH = str(root / "sdcard/labplus/ui.lua")
lua.execute((root / "tests/touch_button.lua").read_text())

lua = LuaRuntime(unpack_returned_tuples=True)
lua.globals().LIMITS_PATH = str(root / 'sdcard/labplus/limits.lua')
lua.globals().PROGRAMS_PATH = str(root / 'sdcard/labplus/programs.lua')
lua.execute((root / 'tests/program_selection.lua').read_text())

lua = LuaRuntime(unpack_returned_tuples=True)
lua.globals().SHELL_PATH = str(root / 'sdcard/labplus/shell.lua')
lua.execute((root / 'tests/product_shell.lua').read_text())

lua = LuaRuntime(unpack_returned_tuples=True)
lua.globals().RESOURCE_PATH = str(root / 'sdcard/labplus/resources.lua')
lua.execute((root / 'tests/resources.lua').read_text())

lua = LuaRuntime(unpack_returned_tuples=True)
lua.globals().TEXT_PATH = str(root / 'sdcard/labplus/text.lua')
lua.execute((root / 'tests/font_resources.lua').read_text())

import runpy
runpy.run_path(str(root / "tests/studio.py"))
