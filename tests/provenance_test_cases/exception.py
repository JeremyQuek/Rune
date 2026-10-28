a=1
try:
    b=a.c.b.d
    raise Exception
except Exception as e: 
    c=1
finally:
    x=1