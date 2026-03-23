import serial
import requests
import time
import threading
from queue import Queue
import config

import debugpy
debugpy.listen(("0.0.0.0", 5678))
#debugpy.wait_for_client()

ser = serial.Serial(config.SERIAL_PORT, config.BAUD, timeout=0.05)

queue = Queue()

status = {}
last_update = 0
UPDATE_INTERVAL = 0.5

# -----------------------
# ОБНОВЛЕНИЕ СТАТУСА
# -----------------------

def update_status():
    global status, last_update
    if time.time() - last_update < UPDATE_INTERVAL:
        return

    try:
        r = requests.get(config.API_STATUS, timeout=0.5).json()["result"]["status"]
        status = r
        #print(r)
        last_update = time.time()
    except:
        pass

# -----------------------
# ОТПРАВКА В KLIPPER
# -----------------------

def send(cmd):
    try:
        resp = requests.post(config.API_CMD, json={"script": cmd}, timeout=1)
        return resp.content
    except:
        pass


# -----------------------
# ТЕМПЕРАТУРА
# -----------------------

def handle_m105(cmd):
    update_status()

    try:
        e = status["extruder"]
        b = status["heater_bed"]

        # Klipper power (0.0 - 1.0)
        e_power = e.get("power", 0.0)
        b_power = b.get("power", 0.0)

        # преобразуем в "Marlin-style" (0-255)
        e_pwm = int(e_power * 255)
        b_pwm = int(b_power * 255)

        return (
            f"ok "
            f"T:{e['temperature']:.1f} /{e['target']:.1f} "
            f"B:{b['temperature']:.1f} /{b['target']:.1f} "
            f"@:{e_pwm} "
            f"B@:{b_pwm}\n"
        )
    except:
        return "ok T:0 /0 B:0 /0 @:0 B@:0\n"

# -----------------------
# ПОЗИЦИЯ
# -----------------------

def handle_m114(cmd):
    update_status()

    try:
        p = status["toolhead"]["position"]
        return f"X:{p[0]:.2f} Y:{p[1]:.2f} Z:{p[2]:.2f}\nok\n"
    except:
        return "ok\n"

# -----------------------
# ПРОГРЕСС
# -----------------------

def handle_m27(cmd):
    update_status()

    try:
        ps = status["print_stats"]
        progress = int(ps["progress"] * 100) if ps["state"] == "printing" else 0
        return f"SD printing byte {progress}/100\nok\n"
    except:
        return "ok\n"

# -----------------------
# ПРОЧИЕ
# -----------------------

def handle_m115(cmd):
    return "FIRMWARE_NAME:Klipper PROTOCOL_VERSION:1.0\nok\n"

def handle_m503(cmd):
    return "Steps per unit:\nM92 X80 Y80 Z400 E93\nok\n"

soft_endstops = True

def handle_m211(cmd):
    global soft_endstops

    # Установка
    if "S0" in cmd:
        soft_endstops = False
    elif "S1" in cmd:
        soft_endstops = True

    # Ответ (Marlin-стиль)
    state = "ON" if soft_endstops else "OFF"

    return f"echo:Soft endstops: {state}\nok\n"

steps = {
    "X": 80.0,
    "Y": 80.0,
    "Z": 400.0,
    "E": 93.0
}

def handle_m92(cmd):
    global steps

    parts = cmd.split()

    # Если есть параметры → обновляем
    if len(parts) > 1:
        for p in parts[1:]:
            axis = p[0]
            value = float(p[1:])

            if axis in steps:
                steps[axis] = value

        # можно попытаться прокинуть в Klipper (опционально)
        # send("SET_EXTRUDER_ROTATION_DISTANCE ...")

    # Ответ (обязателен)
    return (
        f"X:{steps['X']:.2f} "
        f"Y:{steps['Y']:.2f} "
        f"Z:{steps['Z']:.2f} "
        f"E:{steps['E']:.2f}\n"
        "ok\n"
    )


=======
#вентиляторы    
    
def handle_m106(cmd):
    global fan_cache

    parts = cmd.split()

    if len(parts) == 1:
        # это запрос!
        pwm = int(fan_cache * 255)
        return f"Fan:{pwm}\nok\n"

    for p in parts:
        if p.startswith("S"):
            val = int(p[1:])
            fan_cache = val / 255.0
            
    send(cmd)
    return "ok\n"

def handle_m123(cmd):
    pwm = int(fan_cache * 255)
    return f"Fan:{pwm}\nok\n"


# -----------------------
# ПОТОК ОБРАБОТКИ
# -----------------------

def worker():
    while True:
        cmd = queue.get()
        resp = send(cmd)
        print(f"Из очереди {cmd} {resp}")

threading.Thread(target=worker, daemon=True).start()


# -----------------------
# ОСНОВНОЙ ЦИКЛ
# -----------------------

while True:
    try:
        cmd = ser.readline().decode().strip()
        if not cmd:
            continue

        func = cmd.split(" ", 1)[0]

	if func != 'M114' and func != 'M105':
            print(">>", func)

        handler = f"handle_{func.lower()}"
        if handler in globals() and callable(globals()[handler]):
            resp = globals()[handler](cmd)
        else:
            print(f"Функция {handler} не найдена")
            queue.put(cmd)
            resp = "ok\n"

        if func != 'M114' and func != 'M105':
            print("", resp)

        ser.write(resp.encode())

    except Exception as e:
        print("Error:", e)
        time.sleep(1)
