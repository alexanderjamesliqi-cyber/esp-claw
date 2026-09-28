"""MicroPython-to-ESP-Claw bridge for the existing Labplus firmware.

The companion claw_bridge.lua worker must be running. Calls stay on-device.
This module does not provide or replace the underlying MicroPython firmware.
"""
import os
import time
import json

_ROOT = '/sdcard/.mpy_claw'
_sequence = 0


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def call(name, payload=None, timeout_ms=10000):
    """Call a registered ESP-Claw capability and return its JSON/text result.

    A timeout does not cancel a capability already executing. Do not blindly
    retry calls that change hardware or data.
    """
    global _sequence
    if not isinstance(name, str) or not name:
        raise ValueError('name must be a non-empty capability name')
    if timeout_ms < 1 or timeout_ms > 300000:
        raise ValueError('timeout_ms must be in 1..300000')
    os.stat(_ROOT + '/ready.json')
    for attempt in range(32):
        _sequence += 1
        identifier = '%x_%x' % (time.ticks_us(), _sequence)
        folder = _ROOT + '/' + identifier
        try:
            os.mkdir(folder)
            break
        except OSError:
            if attempt == 31:
                raise RuntimeError('Could not allocate a bridge request directory')
    request = {'id': identifier, 'name': name,
               'payload': {} if payload is None else payload}
    try:
        with open(folder + '/request.tmp', 'w') as stream:
            stream.write(json.dumps(request))
        os.rename(folder + '/request.tmp', folder + '/request.json')
        started = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), started) < timeout_ms:
            if name == '__ask':
                try:
                    stream = open(folder + '/status.json')
                except OSError:
                    stream = None
                if stream is not None:
                    with stream:
                        status = json.load(stream)
                    if status.get('id') != identifier:
                        raise RuntimeError('Agent response ID mismatch')
                    with open(folder + '/answer.txt') as answer:
                        result = answer.read()
                    if status.get('status') != 'ok':
                        raise RuntimeError(result)
                    return result
            try:
                stream = open(folder + '/response.json')
            except OSError:
                time.sleep_ms(50)
                continue
            with stream:
                response = json.load(stream)
            if response.get('id') != identifier:
                raise RuntimeError('Bridge response ID mismatch')
            if not response.get('ok'):
                raise RuntimeError(response.get('error', 'ESP-Claw call failed'))
            output = response.get('output')
            if isinstance(output, str):
                try:
                    return json.loads(output)
                except ValueError:
                    pass
            return output
        raise RuntimeError('ESP-Claw bridge timeout; execution may still be in progress')
    finally:
        # Remove the unpublished/request file first, then results. The worker
        # does not recreate a removed request directory after a timed-out call.
        for name in ('request.tmp', 'request.json', 'response.tmp', 'response.json',
                     'answer.txt', 'status.tmp', 'status.json'):
            _remove(folder + '/' + name)
        try:
            os.rmdir(folder)
        except OSError:
            pass


def info():
    return call('get_system_info')


def ask(prompt, timeout_ms=120000):
    """Run the native ESP-Claw agent and wait for its text reply.

    Uses the board's saved LLM configuration and tools. Calls are intended to
    be sequential; a newer agent request can interrupt an older one.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('prompt must be a non-empty string')
    if len(prompt.encode()) > 4096:
        raise ValueError('prompt exceeds 4096 bytes')
    state = info()
    if not state.get('wifi', {}).get('connected'):
        raise RuntimeError('ESP-Claw Wi-Fi is not connected')
    return call('__ask', {'prompt': prompt}, timeout_ms)


run = ask


def voice_start():
    """Start standalone Qwen realtime voice. Requires the rebuilt WebSocket firmware."""
    return call('__voice_start', timeout_ms=20000)


def voice_stop():
    """Stop microphone capture, playback, and the realtime connection."""
    return call('__voice_stop', timeout_ms=20000)


def voice_status():
    return call('__voice_status')


def voice_text(prompt):
    """Send text through the realtime voice session and its ESP-Claw tools."""
    return call('__voice_text', {'prompt': prompt}, timeout_ms=20000)


def voice_press():
    """Begin push-to-talk, interrupting the current spoken reply if needed."""
    return call('__voice_press')


def voice_release():
    """Submit the captured push-to-talk turn (very short presses are discarded)."""
    return call('__voice_release')

def open_page(page="home"):
    """Open home, claw, wifi, library, or the current program output page."""
    return call("__ui_open", {"page":page})

def product_status():
    return call("__product_status")
