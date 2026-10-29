import m                    #m (IMPORT)                                   bound: m
import m as k               #m (IMPORT) ← k                               bound: k
import m.a                  #m (IMPORT) ← m.a                             bound: m
import m.a.b                #m (IMPORT) ← m.a ← m.a.b                     bound: m   (later m.a.b is a chain read)
import m.a.b as k           #m (IMPORT) ← m.a ← m.a.b ← k                 bound: k
from m import a             #m (IMPORT) ← m.a                             bound: a
from m import a as k        #m (IMPORT) ← m.a ← k                         bound: k
from m import a, b          #m (IMPORT) ← m.a, m.b                        bound: a, b
from m.a import b           #m (IMPORT) ← m.a ← m.a.b                     bound: b
from m.a import b as k      #m (IMPORT) ← m.a ← m.a.b ← k                 bound: k
from . import a             #. (IMPORT) ← .a                              bound: a
from .m import a            #. (IMPORT) ← .m ← .m.a                       bound: a
from ..m import a           #.. (IMPORT) ← ..m ← ..m.a                    bound: a
from m import *             #skipped for now

x = len