import xipppy as xp

try:
    xp.xipppy_open()
    print("Connected!")

    print(xp.signal(1, "raw"))

    xp.xipppy_close()

except Exception as e:
    print(e)