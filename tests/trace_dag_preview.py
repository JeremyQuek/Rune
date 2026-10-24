# Open this file in the Rune extension host and hover the variables
# below to preview the trace DAG ("View as graph").
# Straight-line code only, which is all simple_file_analyzer handles.

a = 1
b = 2
c = a + b               # c <- a, b
d = c * a               # d <- c, a  (a is shared: a diamond)
e = d - c + b           # e <- d, c, b
pair = [e, b]           # list, still traced through its elements

name = "rune"
suffix = "!"
greeting = name + suffix
loud = greeting + suffix   # suffix is reached twice
