total = 0
for n in nums:
    if n < 0:
        break
    if n == 0:
        continue
        total = 3
    total += n
else:
    done = True
print(total)
print(done)
