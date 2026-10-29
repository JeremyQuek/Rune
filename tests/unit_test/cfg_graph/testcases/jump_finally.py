for x in xs:
    try:
        if x:
            break
        y = x
    finally:
        cleanup = True
    z = y
print(z)
