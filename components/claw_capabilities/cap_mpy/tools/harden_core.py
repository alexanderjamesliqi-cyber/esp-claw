"""Generate port-local cooperative core sources; never modify the vendor checkout.

Anchors must match exactly. An upstream change fails the build instead of silently
removing a cancellation point. The output diff is retained for review.
"""
import argparse,difflib
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
changes={
'machine_pin.c':[
 ('static mp_obj_t machine_pin_irq(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kw_args) {',
  'static mp_obj_t machine_pin_irq(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kw_args) {\n    mp_raise_NotImplementedError(MP_ERROR_TEXT("Pin IRQ unavailable in managed programs"));',1),
],
'runtime.c':[
 ('mp_obj_t mp_iternext_allow_raise(mp_obj_t o_in) {','mp_obj_t mp_iternext_allow_raise(mp_obj_t o_in) {\n    MICROPY_VM_HOOK_LOOP',1),
 ('mp_obj_t mp_iternext(mp_obj_t o_in) {','mp_obj_t mp_iternext(mp_obj_t o_in) {\n    MICROPY_VM_HOOK_LOOP',1),
],
'mpz.c':[
 ('static size_t mpn_mul_dig_add_dig(mpz_dig_t *idig, size_t ilen, mpz_dig_t dmul, mpz_dig_t dadd) {',
  'static size_t mpn_mul_dig_add_dig(mpz_dig_t *idig, size_t ilen, mpz_dig_t dmul, mpz_dig_t dadd) {\n    MICROPY_VM_HOOK_LOOP',1),
 ('for (; klen > 0; --klen, ++idig, ++kdig) {\n        mpz_dig_t *id = idig;',
  'for (; klen > 0; --klen, ++idig, ++kdig) {\n        MICROPY_VM_HOOK_LOOP\n        mpz_dig_t *id = idig;',1),
 ('while (*num_len > den_len) {','while (*num_len > den_len) {\n        MICROPY_VM_HOOK_LOOP',1),
 ('while (n->len > 0) {','while (n->len > 0) {\n        MICROPY_VM_HOOK_LOOP',2),
 ('bool done;\n    do {\n        mpz_dig_t *d = dig + ilen;',
  'bool done;\n    do {\n        MICROPY_VM_HOOK_LOOP\n        mpz_dig_t *d = dig + ilen;',1),
],
'objstr.c':[
 ('for (;;) {\n            if (memcmp(&haystack[str_index], needle, nlen) == 0) {',
  'for (;;) {\n            if (nlen >= 256 || (str_index & 255) == 0) { MICROPY_VM_HOOK_LOOP }\n            if (memcmp(&haystack[str_index], needle, nlen) == 0) {',1),
 ('for (const byte *haystack_ptr = start; haystack_ptr + needle_len <= end;) {',
  'for (const byte *haystack_ptr = start; haystack_ptr + needle_len <= end;) {\n        if (needle_len >= 256 || ((haystack_ptr - start) & 255) == 0) { MICROPY_VM_HOOK_LOOP }',1),
 ('for (;;) {\n                if (splits == 0 || s + sep_len > top) {',
  'for (;;) {\n                MICROPY_VM_HOOK_LOOP\n                if (splits == 0 || s + sep_len > top) {',1),
 ('for (;;) {\n                if (splits == 0 || s < beg) {',
  'for (;;) {\n                MICROPY_VM_HOOK_LOOP\n                if (splits == 0 || s < beg) {',1),
]}
diff=[]
for name,edits in changes.items():
 source=args.source/name if name!='machine_pin.c' else args.source.parent/'ports/esp32'/name
 original=source.read_text();text=original
 for anchor,replacement,count in edits:
  if text.count(anchor)!=count:raise RuntimeError('MicroPython source changed; review cancellation anchor in '+name+': '+anchor)
  text=text.replace(anchor,replacement)
 destination=args.output/name
 if not destination.exists() or destination.read_text()!=text:destination.write_text(text)
 diff.extend(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile='upstream/'+name,tofile='managed/'+name))
(args.output/'cooperative-core.patch').write_text(''.join(diff))
