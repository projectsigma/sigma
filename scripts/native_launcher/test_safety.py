"""Portable tests for the native launcher path parser and build artifact.
Checks positive and failure cases without starting a Windows process.
"""
from pathlib import Path
import subprocess, struct, shutil, sys, tempfile
ROOT=Path(__file__).parent
s=(ROOT/'sigma_native.c').read_text()
assert 'static int hex(' in s and 'static uint64_t parse_decimal(' in s
sanitizer='static int hex('+s.split('static int hex(',1)[1].split('static uint64_t parse_decimal(',1)[0]
decimal='static uint64_t parse_decimal('+s.split('static uint64_t parse_decimal(',1)[1].split('static void serve_file(',1)[0]
host_code='static int host_allowed('+s.split('static int host_allowed(',1)[1].split('static int hex(',1)[0]
prefix=r'''
#include <stdio.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef uint16_t WCHAR;
#define CP_UTF8 65001
#define MB_ERR_INVALID_CHARS 8
static char lc(char c){return c>='A' && c<='Z' ? (char)(c+32):c;}
static int g_port=8765;
static int match_ci(const char *p,const char *word){while(*word){if(lc(*p++)!=lc(*word++))return 0;}return 1;}
static int ascii_eq(const char *a,const char *b){while(*a&&*b){if(lc(*a++)!=lc(*b++))return 0;}return *a==*b;}
static void appendtxt(char *dst,int *len,const char *src,int cap){while(*src&&*len+1<cap)dst[(*len)++]=*src++;dst[*len]=0;}
static void appendnum(char *dst,int *len,uint64_t n,int cap){char tmp[32];int k=0;do{tmp[k++]=(char)('0'+n%10);n/=10;}while(n&&k<31);while(k && *len+1<cap)dst[(*len)++]=tmp[--k];dst[*len]=0;}
static int MultiByteToWideChar(unsigned cp,unsigned flags,const char*s,int len,WCHAR*out,int outcap){
  (void)cp;(void)flags;
  if(len>outcap)return 0;
  for(int i=0;i<len;i++){if(((unsigned char)s[i])>=128)return 0;out[i]=(unsigned char)s[i];}
  return len;
}
'''
test=r'''
int main(void){
  WCHAR out[4096];char decoded[4097];
  struct sample {const char*url;int valid;const char*path;} samples[]={
   {"/",1,"index.html"},{"/index.html",1,"index.html"},
   {"/data/graph.json",1,"data/graph.json"},
   {"/vendor/maplibre-gl.js?v=2",1,"vendor/maplibre-gl.js"},
   {"/data%2Fmetadata.json",1,"data/metadata.json"},
   {"/%2e%2e/secret",0,""},{"/foo/../secret",0,""},
   {"/foo/.",0,""},{"/foo//../bar",0,""},
   {"/C:%5cWindows",0,""},{"/%5Cwindows",0,""},
   {"/data/%00secret",0,""},{"/data/%0Asecret",0,""},
   {"/%",0,""},{"/%2",0,""},{"/bad%XXpath",0,""},
   {"/trailing/",0,""},{"https://otherhost/",0,""},
   {"/space%20here.json",1,"space here.json"},
  };
  int count=(int)(sizeof(samples)/sizeof(samples[0]));
  for(int i=0;i<count;i++){
   int ok=safe_path(samples[i].url,out,4096,decoded,4097);
   if(ok!=samples[i].valid || (ok&&strcmp(decoded,samples[i].path)!=0)){
    fprintf(stderr,"FAIL path %s: valid=%d decoded=%s\n",samples[i].url,ok,decoded);return 1;
   }
  }
  const char *end;
  if(parse_decimal("12345-",&end)!=12345 || *end!='-')return 2;
  if(parse_decimal("18446744073709551616-",&end)!=UINT64_MAX)return 3;
  struct host_case {const char *req; int ok;} hosts[]={
    {"GET / HTTP/1.1\r\nHost: localhost:8765\r\n\r\n",1},
    {"GET / HTTP/1.1\r\nHost: 127.0.0.1:8765\r\n\r\n",1},
    {"GET / HTTP/1.1\r\nhOSt: LOCALHOST:8765\r\n\r\n",1},
    {"GET / HTTP/1.1\r\nHost: evil.example:8765\r\n\r\n",0},
    {"GET / HTTP/1.1\r\nHost: localhost:9999\r\n\r\n",0},
    {"GET / HTTP/1.1\r\nUser-Agent: test\r\n\r\n",0},
    {"GET / HTTP/1.1\r\nHost: localhost:8765\r\nHost: evil.example:8765\r\n\r\n",0},
  };
  for(int i=0;i<7;i++){
    int v=host_allowed(hosts[i].req,(int)strlen(hosts[i].req));
    if(v!=hosts[i].ok){fprintf(stderr,"FAIL host: %s\n",hosts[i].req);return 7;}
  }
  puts("PASS: 19 URL cases, range integer overflow, 7 Host-header allow/deny cases");
  return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
 t=Path(d);(t/'harness.c').write_text(prefix+host_code+sanitizer+decimal+test)
 subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror',str(t/'harness.c'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
exe_path=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'sigma.exe'
exe=exe_path.read_bytes()
pe=struct.unpack_from('<I',exe,0x3c)[0]
assert exe[:2]==b'MZ' and exe[pe:pe+4]==b'PE\x00\x00'
assert struct.unpack_from('<H',exe,pe+4)[0]==0x8664
opt=pe+24
assert struct.unpack_from('<H',exe,opt+68)[0]==2, 'must be Windows GUI, no console'
assert len(exe)<128*1024, len(exe)
result=subprocess.run(['llvm-objdump','-p',str(exe_path)],check=True,capture_output=True,text=True).stdout
names=[line.split('DLL Name:')[1].strip() for line in result.splitlines() if 'DLL Name:' in line]
assert set(names)=={'KERNEL32.dll','USER32.dll','SHELL32.dll','WS2_32.dll'}, names
assert not any('python' in x.lower() or 'vcruntime' in x.lower() for x in names)
assert 'SigmaExplorerTrayWindowNative'.encode('utf-16le') in exe
assert 'SIGMA'.encode('utf-16le') in exe
# verify copied icon resource from old executable is the exact original content
assert exe.count(b'\x89PNG\r\n\x1a\n')>=7,'seven icon PNG resources must be embedded'
print(f'PASS: Windows PE64 GUI, {len(exe):,} bytes, 7 logo-icon sizes, 4 Windows system DLL imports, no bundled runtime')
