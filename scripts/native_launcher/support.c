#include <stddef.h>
void *memset(void *dst, int value, size_t n) {
  unsigned char *p=(unsigned char*)dst;
  while(n--) *p++=(unsigned char)value;
  return dst;
}
