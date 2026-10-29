nums = [1, 2, 3, 4, 5]
total = 0
for n in nums:
    if n % 2 == 0:
        total += n
    else:
        total -= n
else:
    done = True
    total *= 2
print(total)
