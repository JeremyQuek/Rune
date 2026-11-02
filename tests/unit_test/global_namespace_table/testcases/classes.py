class A:
    def __init__(this, n):
        this.x = 1                  # instance x, receiver named "this"
        this.y: int = n             # instance y
        for i in range(3):
            this.x += i             # instance x, once despite the loop passes
        this.a.b = 2                # skipped: two levels, belongs to a's type
        def inner(self):
            self.z = 3              # skipped: nested function, no receiver

    @classmethod
    def make(cls):
        cls.count = 0               # class count

    @staticmethod
    def util(self):
        self.no = 1                 # skipped: static, no receiver

    def reset(self, other):
        self.x = ""                 # instance x again: a second declaration
        self = other
        self.gone = 1               # skipped: receiver rebound


class Outer(A):
    def f(self):
        class Inner:                # Outer.Inner: the method f is skipped in the key
            def g(self):
                self.deep = True


if A:
    class B: pass                   # two rows: same name, different sites
else:
    class B: pass
