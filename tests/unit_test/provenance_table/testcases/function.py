x =1
def func():
    global x
    b =x


def func(a, b:int, c=4):
    nonlocal x
    d = a + b 
    print(d)

    e = c

    return d