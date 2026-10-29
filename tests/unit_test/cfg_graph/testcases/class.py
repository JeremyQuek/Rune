class Counter:
    start = 0

    def __init__(self, step: int):
        self.count = Counter.start
        self.step = step

    def tick(self):
        self.count = self.count + self.step
        return self.count

    def reset(self, to=0):
        self.count = to


c = Counter(2)
c.tick()
n = c.tick()
c.reset()
