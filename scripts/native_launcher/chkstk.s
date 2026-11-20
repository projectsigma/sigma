.text
.globl __chkstk
__chkstk:
  pushq %rcx
  pushq %rax
  cmpq $0x1000, %rax
  leaq 24(%rsp), %rcx
  jb 2f
1:
  subq $0x1000, %rcx
  testb %al, (%rcx)
  subq $0x1000, %rax
  cmpq $0x1000, %rax
  ja 1b
2:
  subq %rax, %rcx
  testb %al, (%rcx)
  popq %rax
  popq %rcx
  retq
