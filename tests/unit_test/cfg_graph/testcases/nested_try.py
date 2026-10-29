try:
    a = 1
    try:
        if a:
            raise ValueError
        b = 2
    except KeyError:
        c = 3
    finally:
        inner = True
    d = 4
except ValueError as e:
    f = 5
finally:
    outer = True
print(a)
