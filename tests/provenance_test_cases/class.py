"""Simple class snippets for testing Rune's type inference."""

from dataclasses import dataclass


class Point:
    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y
        self.label = "pt"            # expect: str

    def total(self):
        return self.x + self.y       # expect: int


class Animal:
    def __init__(self, name: str) -> None:
        self.name = name

    def speak(self) -> str:
        return "..."


class Dog(Animal):
    def speak(self) -> str:
        return self.name + " barks"  # expect: str (name from Animal)


@dataclass
class User:
    id: int
    email: str


# Usage sites
p = Point(1, 2)
s = p.total()                        # expect: int
d = Dog("Rex")
msg = d.speak()                      # expect: str
u = User(1, "a@b.com")
e = u.email                          # expect: str