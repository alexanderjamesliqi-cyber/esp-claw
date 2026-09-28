a=(1<<4096)+123456789
b=(1<<2049)+98765
assert (a*b)//b==a
assert divmod(a*b+17,b)==(a,17)
assert int(str(a))==a
assert ((7**173)%1000000007)==568193094
assert 'abcabc'.count('ab')==2
assert 'a-b-c'.split('-')==['a','b','c']
assert 'a-b-c'.rsplit('-',1)==['a-b','c']
print('ARITHMETIC_OK')
