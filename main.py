from machine import Pin, PWM, ADC, I2C
import time, ujson, os
import ssd1306_custom

# -----------------------
#   BOUTONS & OLED
# -----------------------
BTN_UP = Pin(2, Pin.IN, Pin.PULL_UP)
BTN_DOWN = Pin(3, Pin.IN, Pin.PULL_UP)
BTN_OK = Pin(4, Pin.IN, Pin.PULL_UP)
BTN_CANCEL = Pin(5, Pin.IN, Pin.PULL_UP)

i2c = I2C(0, scl=Pin(1), sda=Pin(0), freq=400000)
oled = ssd1306_custom.SSD1306_I2C(128, 64, i2c)

menu_stack = []
current_menu = "root"
selected = 0
active_instr = 0       # 0..3
play_mode = False      # False = MENU, True = JEU

# -----------------------
#   FICHIERS INSTRUMENTS
# -----------------------
INSTR_FILES = [
    "voix1.cfg",
    "voix2.cfg",
    "voix3.cfg",
    "voix4.cfg"
]

# Paramètres par défaut (ceux de ton premier code)
DEFAULT_PATCH = {
    "maxlevel": 0.3,
    "dutycycle": 0.3,
    "slidemode": "Q",   # "Q" ou "noQ"
    "attack": 0.0,
    "decay": 0.4,
    "sustain": 0.2,
    "release": 0.4
}

def init_instruments():
    for fname in INSTR_FILES:
        if fname not in os.listdir():
            with open(fname, "w") as f:
                f.write(ujson.dumps(DEFAULT_PATCH))

def load_instr(index):
    fname = INSTR_FILES[index]
    try:
        with open(fname, "r") as f:
            data = ujson.loads(f.read())
    except:
        data = DEFAULT_PATCH.copy()

    for key, value in DEFAULT_PATCH.items():
        if key not in data:
            data[key] = value

    return data

def save_instr(index, data):
    fname = INSTR_FILES[index]
    with open(fname, "w") as f:
        f.write(ujson.dumps(data))

# -----------------------
#   MENU STRUCTURE
# -----------------------
menu = {
    "root": [
        ("Voix 1", "voix1"),
        ("Voix 2", "voix2"),
        ("Voix 3", "voix3"),
        ("Voix 4", "voix4"),
    ],
}

for i in range(4):
    menu[f"voix{i+1}"] = [
        ("Form", f"form{i+1}"),
        ("ADSR", f"adsr{i+1}"),
        ("Slide", f"slide{i+1}")
    ]

    menu[f"form{i+1}"] = [
        ("Max", ("form", "maxlevel", i)),
        ("Dty", ("form", "dutycycle", i))
    ]

    menu[f"adsr{i+1}"] = [
        ("Attack", ("adsr", "attack", i)),
        ("Decay", ("adsr", "decay", i)),
        ("Sustain", ("adsr", "sustain", i)),
        ("Release", ("adsr", "release", i)),
    ]

    menu[f"slide{i+1}"] = [
        ("Q", ("slide", "Q", i)),
        ("noQ", ("slide", "noQ", i))
    ]

def draw_menu_vertical():
    oled.fill(0)
    items = menu[current_menu]
    x_start = 10

    for i, (label, target) in enumerate(items):
        x = x_start + i * 30
        display_label = label

        # Root : marquer la voix active
        if current_menu == "root":
            if i == active_instr:
                display_label = f"$£{label}"

        # Form
        if isinstance(target, tuple) and target[0] == "form":
            _, name, instr = target
            current = load_instr(instr)[name]
            display_label = f"{label} {round(current, 1)}"

        # ADSR
        if isinstance(target, tuple) and target[0] == "adsr":
            _, name, instr = target
            current = load_instr(instr)[name]
            display_label = f"{label} {round(current, 1)}"

        # Slide
        if isinstance(target, tuple) and target[0] == "slide":
            _, value, instr = target
            current = load_instr(instr)["slidemode"]
            if value == current:
                display_label = f"$£{label}"

        # highlight
        if i == selected:
            oled.fill_rect(x - 2, 0, 28, 64, 1)
            oled.text90(display_label, x, 63, color=0)
        else:
            oled.text90(display_label, x, 63, color=1)

    oled.show()

def wait_release(pin):
    while pin.value() == 0:
        time.sleep(0.02)

# -----------------------
#   MOTEUR SONORE
# -----------------------
# Entrées analogiques
pot1 = ADC(Pin(26))
pot2 = ADC(Pin(27))
pot3 = ADC(Pin(28))

# Sorties PWM
pwm1 = PWM(Pin(10))
pwm2 = PWM(Pin(15))
pwm3 = PWM(Pin(20))

# Réglettes calibrées
CALIB_24_1 = [
    0.02, 0.13, 0.25, 0.37, 0.46, 0.56, 0.65, 0.75,
    0.84, 0.94, 1.04, 1.14, 1.24, 1.35, 1.46, 1.58,
    1.73, 1.88, 2.05, 2.25, 2.45, 2.68, 2.99, 3.25
]

CALIB_24_2 = [
    0.02, 0.16, 0.28, 0.40, 0.49, 0.59, 0.69, 0.79,
    0.89, 0.99, 1.10, 1.20, 1.30, 1.41, 1.53, 1.65,
    1.78, 1.93, 2.09, 2.27, 2.47, 2.69, 2.94, 3.25
]

# Notes
NOTES_24 = [
    261.63, 277.18, 293.66, 311.13, 329.63, 349.23,
    369.99, 392.00, 415.30, 440.00, 466.16, 493.88,
    523.25, 554.37, 587.33, 622.25, 659.25, 698.46,
    739.99, 783.99, 830.61, 880.00, 932.33, 987.77
]

# Paramètres courants du moteur (chargés depuis la voix active)
ATTACK = 0.0
DECAY = 0.4
SUSTAIN_LEVEL = 0.2
RELEASE = 0.4
MAX_LEVEL = 0.3
PULSE_WIDTH = 0.3
SLIDE_MODE = "Q"   # "Q" ou "noQ"

def apply_patch_to_engine(patch):
    global ATTACK, DECAY, SUSTAIN_LEVEL, RELEASE, MAX_LEVEL, PULSE_WIDTH, SLIDE_MODE

    # ATTACK = 0 → attaque minimale (0.001 s)
    atk = patch["attack"]
    if atk <= 0:
        atk = 0.001

    dec = patch["decay"]
    if dec <= 0:
        dec = 0.001

    rel = patch["release"]
    if rel <= 0:
        rel = 0.001

    ATTACK = atk
    DECAY = dec
    SUSTAIN_LEVEL = patch["sustain"]
    RELEASE = rel
    MAX_LEVEL = patch["maxlevel"]
    PULSE_WIDTH = patch["dutycycle"]
    SLIDE_MODE = patch["slidemode"]

def apply_adsr(note_on, note_off):
    now = time.ticks_ms() / 1000.0

    if note_on is not None:
        t = now - note_on

        # ATTACK
        if t < ATTACK:
            level = (t / ATTACK) * MAX_LEVEL
            return int(65535 * level)

        # DECAY
        elif t < ATTACK + DECAY:
            d = (t - ATTACK) / DECAY
            if d < 0:
                d = 0
            if d > 1:
                d = 1
            level = MAX_LEVEL + (SUSTAIN_LEVEL - MAX_LEVEL) * d
            return int(65535 * level)

        # SUSTAIN
        else:
            return int(65535 * SUSTAIN_LEVEL)

    # RELEASE
    if note_off is not None:
        t = now - note_off
        if t < RELEASE:
            start = int(65535 * SUSTAIN_LEVEL)
            return int(start * (1 - t / RELEASE))
        else:
            return 0

    return 0

def closest_note_index(v, table):
    best_i = 0
    best_diff = abs(v - table[0])
    for i in range(1, len(table)):
        d = abs(v - table[i])
        if d < best_diff:
            best_diff = d
            best_i = i
    return best_i

def interpolated_freq(v, table):
    idx = closest_note_index(v, table)

    if idx == 0:
        return NOTES_24[0]
    if idx == len(table) - 1:
        return NOTES_24[-1]

    v_low = table[idx]
    v_high = table[idx + 1] if v > v_low else table[idx - 1]

    f_low = NOTES_24[idx]
    f_high = NOTES_24[idx + 1] if v > v_low else NOTES_24[idx - 1]

    position = (v - v_low) / (v_high - v_low)
    return f_low + position * (f_high - f_low)

def quantized_freq(v, table):
    idx = closest_note_index(v, table)
    return NOTES_24[idx]

# États des notes
note_on_time1 = None; note_off_time1 = None; playing1 = False
note_on_time2 = None; note_off_time2 = None; playing2 = False
note_on_time3 = None; note_off_time3 = None; playing3 = False

# -----------------------
#   INITIALISATION
# -----------------------
init_instruments()
current_patch = load_instr(active_instr)
apply_patch_to_engine(current_patch)
draw_menu_vertical()

# -----------------------
#   BOUCLE PRINCIPALE
# -----------------------
while True:
    
    # ----- MODE JEU -----
    if play_mode:
        # en mode PLAY, seul OK permet de revenir au menu
        if BTN_OK.value() == 0:
            play_mode = False
            current_menu = "root"
            selected = active_instr
            draw_menu_vertical()
            wait_release(BTN_OK)
        time.sleep(0.01)
        continue
    
    # ----- MOTEUR SONORE (TOUJOURS ACTIF) -----
    v1 = pot1.read_u16() * 3.3 / 65535
    v2 = pot2.read_u16() * 3.3 / 65535
    v3 = pot3.read_u16() * 3.3 / 65535

    # CANAL 1
    if v1 < 0.05:
        if playing1:
            note_off_time1 = time.ticks_ms() / 1000.0
            note_on_time1 = None
            playing1 = False
        adsr = apply_adsr(note_on_time1, note_off_time1)
        duty = int(adsr * PULSE_WIDTH)
        if duty > 65535:
            duty = 65535
        pwm1.duty_u16(duty)
    else:
        if not playing1:
            note_on_time1 = time.ticks_ms() / 1000.0
            note_off_time1 = None
            playing1 = True

        if SLIDE_MODE == "noQ":
            f1 = interpolated_freq(v1, CALIB_24_1)
        else:
            f1 = quantized_freq(v1, CALIB_24_1)

        pwm1.freq(int(f1))
        adsr = apply_adsr(note_on_time1, note_off_time1)
        duty = int(adsr * PULSE_WIDTH)
        if duty > 65535:
            duty = 65535
        pwm1.duty_u16(duty)

    # CANAL 2
    if v2 < 0.05:
        if playing2:
            note_off_time2 = time.ticks_ms() / 1000.0
            note_on_time2 = None
            playing2 = False
        adsr = apply_adsr(note_on_time2, note_off_time2)
        duty = int(adsr * PULSE_WIDTH)
        if duty > 65535:
            duty = 65535
        pwm2.duty_u16(duty)
    else:
        if not playing2:
            note_on_time2 = time.ticks_ms() / 1000.0
            note_off_time2 = None
            playing2 = True

        if SLIDE_MODE == "noQ":
            f2 = interpolated_freq(v2, CALIB_24_2)
        else:
            f2 = quantized_freq(v2, CALIB_24_2)

        pwm2.freq(int(f2))
        adsr = apply_adsr(note_on_time2, note_off_time2)
        duty = int(adsr * PULSE_WIDTH)
        if duty > 65535:
            duty = 65535
        pwm2.duty_u16(duty)

    # CANAL 3
    if v3 < 0.05:
        if playing3:
            note_off_time3 = time.ticks_ms() / 1000.0
            note_on_time3 = None
            playing3 = False
        adsr = apply_adsr(note_on_time3, note_off_time3)
        duty = int(adsr * PULSE_WIDTH)
        if duty > 65535:
            duty = 65535
        pwm3.duty_u16(duty)
    else:
        if not playing3:
            note_on_time3 = time.ticks_ms() / 1000.0
            note_off_time3 = None
            playing3 = True

        if SLIDE_MODE == "noQ":
            f3 = interpolated_freq(v3, CALIB_24_2)
        else:
            f3 = quantized_freq(v3, CALIB_24_2)

        pwm3.freq(int(f3))
        adsr = apply_adsr(note_on_time3, note_off_time3)
        duty = int(adsr * PULSE_WIDTH)
        if duty > 65535:
            duty = 65535
        pwm3.duty_u16(duty)

    # ----- MODE MENU -----
    if BTN_UP.value() == 0:
        selected = (selected + 1) % len(menu[current_menu])
        draw_menu_vertical()
        wait_release(BTN_UP)

    if BTN_DOWN.value() == 0:
        selected = (selected - 1) % len(menu[current_menu])
        draw_menu_vertical()
        wait_release(BTN_DOWN)

    if BTN_OK.value() == 0:
        label, target = menu[current_menu][selected]

        # navigation vers sous-menu voixX
        if isinstance(target, str) and target in menu:

            # Ne changer de voix que si on est dans root
            if current_menu == "root":
                active_instr = selected
                current_patch = load_instr(active_instr)
                apply_patch_to_engine(current_patch)

            menu_stack.append(current_menu)
            current_menu = target
            selected = 0
            wait_release(BTN_OK)
            draw_menu_vertical()
            continue

        # Form sliders (maxlevel / dutycycle)
        if isinstance(target, tuple) and target[0] == "form":
            _, name, instr = target
            wait_release(BTN_OK)

            data = load_instr(instr)
            value = data[name]

            while True:
                oled.fill(0)
                oled.text90(name, 0, 63, 1)
                oled.text90("Value", 20, 63, 1)
                oled.text90(str(round(value, 1)), 40, 63, 1)
                oled.show()

                if BTN_UP.value() == 0:
                    value = min(10.0, value + 0.1)
                    wait_release(BTN_UP)

                if BTN_DOWN.value() == 0:
                    value = max(0.0, value - 0.1)
                    wait_release(BTN_DOWN)

                if BTN_OK.value() == 0:
                    data[name] = value
                    save_instr(instr, data)
                    if instr == active_instr:
                        apply_patch_to_engine(data)
                    wait_release(BTN_OK)
                    break

                if BTN_CANCEL.value() == 0:
                    wait_release(BTN_CANCEL)
                    break

            draw_menu_vertical()

        # ADSR sliders
        elif isinstance(target, tuple) and target[0] == "adsr":
            _, name, instr = target
            wait_release(BTN_OK)

            data = load_instr(instr)
            value = data[name]

            while True:
                oled.fill(0)
                oled.text90(name, 0, 63, 1)
                oled.text90("Value", 20, 63, 1)
                oled.text90(str(round(value, 1)), 40, 63, 1)
                oled.show()

                if BTN_UP.value() == 0:
                    value = min(10.0, value + 0.1)
                    wait_release(BTN_UP)

                if BTN_DOWN.value() == 0:
                    value = max(0.0, value - 0.1)
                    wait_release(BTN_DOWN)

                if BTN_OK.value() == 0:
                    data[name] = value
                    save_instr(instr, data)
                    if instr == active_instr:
                        apply_patch_to_engine(data)
                    wait_release(BTN_OK)
                    break

                if BTN_CANCEL.value() == 0:
                    wait_release(BTN_CANCEL)
                    break

            draw_menu_vertical()

        # Slide mode (Q / noQ)
        elif isinstance(target, tuple) and target[0] == "slide":
            _, value, instr = target
            wait_release(BTN_OK)

            data = load_instr(instr)
            data["slidemode"] = value
            save_instr(instr, data)
            if instr == active_instr:
                apply_patch_to_engine(data)

            draw_menu_vertical()
            continue

    # CANCEL = retour ou passage en mode PLAY
    if BTN_CANCEL.value() == 0:
        if current_menu == "root":
            play_mode = True
            oled.fill(0)
            oled.text90("Notice :", 100, 63, 1)
            oled.text90("bit.ly/", 70, 63, 1)
            oled.text90("Spectro", 40, 63, 1)
            oled.text90("Synth", 10, 63, 1)
            oled.show()
            wait_release(BTN_CANCEL)
            continue

        if menu_stack:
            current_menu = menu_stack.pop()
            selected = 0
            draw_menu_vertical()
        wait_release(BTN_CANCEL)


    time.sleep(0.01)
