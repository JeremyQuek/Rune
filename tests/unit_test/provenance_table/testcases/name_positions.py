"""
Name positions the AST does and doesn't record.
A bare string field (name=, asname=, rest=, names=[...]) has NO position of its own:
the key must come from the source text. A Name/arg node carries its own position.
Each statement is followed by its AST (cols are 0-based, lines 1-based). Generated with Python 3.14.3.
"""

class Point:
    pass
#   ClassDef name='Point'  (col 0-8, line 1-2)
#     body=Pass  (col 4-8, line 2-2)

def total(a, b):
    return a
#   FunctionDef name='total'  (col 0-12, line 4-5)
#     args=arguments
#       args=arg arg='a'  (col 10-11, line 4-4)
#       args=arg arg='b'  (col 13-14, line 4-4)
#     body=Return  (col 4-12, line 5-5)
#       value=Name id='a'  (col 11-12, line 5-5)

async def fetch(url):
    pass
#   AsyncFunctionDef name='fetch'  (col 0-8, line 7-8)
#     args=arguments
#       args=arg arg='url'  (col 16-19, line 7-7)
#     body=Pass  (col 4-8, line 8-8)

e = 1
#   Assign  (col 0-5, line 10-10)
#     targets=Name id='e'  (col 0-1, line 10-10)
#     value=Constant value=1  (col 4-5, line 10-10)

while e:
    e = 0
#   While  (col 0-9, line 11-12)
#     test=Name id='e'  (col 6-7, line 11-11)
#     body=Assign  (col 4-9, line 12-12)
#       targets=Name id='e'  (col 4-5, line 12-12)
#       value=Constant value=0  (col 8-9, line 12-12)

for i in range(3):
    pass
#   For  (col 0-8, line 14-15)
#     target=Name id='i'  (col 4-5, line 14-14)
#     iter=Call  (col 9-17, line 14-14)
#       func=Name id='range'  (col 9-14, line 14-14)
#       args=Constant value=3  (col 15-16, line 14-14)
#     body=Pass  (col 4-8, line 15-15)

with open("f.txt") as f:
    pass
#   With  (col 0-8, line 17-18)
#     items=withitem
#       context_expr=Call  (col 5-18, line 17-17)
#         func=Name id='open'  (col 5-9, line 17-17)
#         args=Constant value='f.txt'  (col 10-17, line 17-17)
#       optional_vars=Name id='f'  (col 22-23, line 17-17)
#     body=Pass  (col 4-8, line 18-18)

try:
    pass
except Exception as err:
    pass
#   Try  (col 0-8, line 20-23)
#     body=Pass  (col 4-8, line 21-21)
#     handlers=ExceptHandler name='err'  (col 0-8, line 22-23)
#       type=Name id='Exception'  (col 7-16, line 22-22)
#       body=Pass  (col 4-8, line 23-23)

import os.path as osp
#   Import  (col 0-21, line 25-25)
#     names=alias name='os.path' asname='osp'  (col 7-21, line 25-25)

from os import path as p
#   ImportFrom module='os'  (col 0-24, line 27-27)
#     names=alias name='path' asname='p'  (col 15-24, line 27-27)

def scoped():
    global e
    nonlocal_free = 1
#   FunctionDef name='scoped'  (col 0-21, line 29-31)
#     args=arguments
#     body=Global names=['e']  (col 4-12, line 30-30)
#     body=Assign  (col 4-21, line 31-31)
#       targets=Name id='nonlocal_free'  (col 4-17, line 31-31)
#       value=Constant value=1  (col 20-21, line 31-31)

match e:
    case [first, *rest]:
        pass
    case {"k": v, **others}:
        pass
    case Point() as pt:
        pass
#   Match  (col 0-12, line 33-39)
#     subject=Name id='e'  (col 6-7, line 33-33)
#     cases=match_case
#       pattern=MatchSequence  (col 9-23, line 34-34)
#         patterns=MatchAs name='first'  (col 10-15, line 34-34)
#         patterns=MatchStar name='rest'  (col 17-22, line 34-34)
#       body=Pass  (col 8-12, line 35-35)
#     cases=match_case
#       pattern=MatchMapping rest='others'  (col 9-27, line 36-36)
#         keys=Constant value='k'  (col 10-13, line 36-36)
#         patterns=MatchAs name='v'  (col 15-16, line 36-36)
#       body=Pass  (col 8-12, line 37-37)
#     cases=match_case
#       pattern=MatchAs name='pt'  (col 9-22, line 38-38)
#         pattern=MatchClass  (col 9-16, line 38-38)
#           cls=Name id='Point'  (col 9-14, line 38-38)
#       body=Pass  (col 8-12, line 39-39)

y = (w := 5)
#   Assign  (col 0-12, line 41-41)
#     targets=Name id='y'  (col 0-1, line 41-41)
#     value=NamedExpr  (col 5-11, line 41-41)
#       target=Name id='w'  (col 5-6, line 41-41)
#       value=Constant value=5  (col 10-11, line 41-41)

g = lambda q: q
#   Assign  (col 0-15, line 43-43)
#     targets=Name id='g'  (col 0-1, line 43-43)
#     value=Lambda  (col 4-15, line 43-43)
#       args=arguments
#         args=arg arg='q'  (col 11-12, line 43-43)
#       body=Name id='q'  (col 14-15, line 43-43)

