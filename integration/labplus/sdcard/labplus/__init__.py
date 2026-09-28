"""Board helpers that share the active UI instead of taking over LCD/I2S."""
def display_text(text):
    import esp_claw
    return esp_claw.call('__display_text', {'text':str(text)})
def button_pressed():
    from machine import Pin
    return Pin(35, Pin.IN, Pin.PULL_UP).value() == 0


def countdown(seconds=10):
    """Display a bounded countdown using the board UI and monotonic time."""
    import time
    if not isinstance(seconds, int) or seconds < 0 or seconds > 59:
        raise ValueError('seconds must be an integer in 0..59')
    started=time.ticks_ms()
    previous=None
    while True:
        elapsed=time.ticks_diff(time.ticks_ms(),started)
        left=max(0,(seconds*1000-elapsed+999)//1000)
        if left!=previous:
            display_text(str(left) if left else '0\n时间到')
            previous=left
        if left==0:
            break
        time.sleep_ms(50)
