/* SIGMA Explorer — Windows-only native, local-loopback, read-only static launcher.
   Compiled freestanding for Win64, without the C runtime or Python.
   sigma.exe lives INSIDE the exported Explorer directory.
*/
#include <stdint.h>
#include <stddef.h>

typedef void *HANDLE, *HINSTANCE, *HWND, *HICON, *HMENU, *HBRUSH;
typedef const void *LPCVOID;
typedef void *LPVOID;
typedef uint16_t WCHAR, WORD;
typedef uint32_t DWORD, UINT, ULONG;
typedef uint64_t WPARAM, ULONG_PTR, SOCKET;
typedef int64_t LPARAM, LRESULT, LONG_PTR;
typedef int BOOL;
typedef unsigned char BYTE;
typedef struct { long x, y; } POINT;
typedef LRESULT (__stdcall *WNDPROC)(HWND,UINT,WPARAM,LPARAM);
typedef struct { UINT cbSize; HWND hwnd; UINT message; WPARAM wParam; LPARAM lParam; DWORD time; POINT pt; DWORD lPrivate; } MSG;
typedef struct { UINT style; WNDPROC lpfnWndProc; int cbClsExtra; int cbWndExtra; HINSTANCE hInstance; HICON hIcon; void *hCursor; HBRUSH hbrBackground; const WCHAR *lpszMenuName; const WCHAR *lpszClassName; } WNDCLASSW;
typedef struct { DWORD Data1; WORD Data2,Data3; BYTE Data4[8]; } GUID;
typedef struct { DWORD cbSize; HWND hWnd; UINT uID; UINT uFlags; UINT uCallbackMessage; HICON hIcon; WCHAR szTip[128]; DWORD dwState; DWORD dwStateMask; WCHAR szInfo[256]; UINT uTimeout; WCHAR szInfoTitle[64]; DWORD dwInfoFlags; GUID guidItem; HICON hBalloonIcon; } NOTIFYICONDATAW;
typedef struct { uint16_t sin_family, sin_port; uint32_t sin_addr; BYTE sin_zero[8]; } SOCKADDR_IN;

#define IN(name, ret, ...) __declspec(dllimport) ret __stdcall name(__VA_ARGS__)
IN(GetModuleHandleW,HINSTANCE,const WCHAR*);
IN(GetModuleFileNameW,DWORD,HINSTANCE,WCHAR*,DWORD);
IN(GetFileAttributesW,DWORD,const WCHAR*);
IN(CreateFileW,HANDLE,const WCHAR*,DWORD,DWORD,LPVOID,DWORD,DWORD,HANDLE);
IN(GetFileSizeEx,BOOL,HANDLE,int64_t*);
IN(SetFilePointerEx,BOOL,HANDLE,int64_t,int64_t*,DWORD);
IN(ReadFile,BOOL,HANDLE,LPVOID,DWORD,DWORD*,LPVOID);
IN(CloseHandle,BOOL,HANDLE);
IN(GetFinalPathNameByHandleW,DWORD,HANDLE,WCHAR*,DWORD,DWORD);
IN(CreateThread,HANDLE,LPVOID,size_t,DWORD (__stdcall *)(LPVOID),LPVOID,DWORD,DWORD*);
IN(WaitForSingleObject,DWORD,HANDLE,DWORD);
IN(CreateMutexW,HANDLE,LPVOID,BOOL,const WCHAR*);
IN(GetLastError,DWORD,void);
IN(Sleep,void,DWORD);
IN(GetProcessHeap,HANDLE,void);
IN(HeapAlloc,LPVOID,HANDLE,DWORD,size_t);
IN(HeapFree,BOOL,HANDLE,DWORD,LPVOID);
IN(MultiByteToWideChar,int,UINT,DWORD,const char*,int,WCHAR*,int);
IN(CompareStringOrdinal,int,const WCHAR*,int,const WCHAR*,int,BOOL);
IN(GlobalAlloc,HANDLE,UINT,size_t);
IN(GlobalLock,LPVOID,HANDLE);
IN(GlobalUnlock,BOOL,HANDLE);
IN(GlobalFree,HANDLE,HANDLE);
IN(RegisterClassW,WORD,const WNDCLASSW*);
IN(CreateWindowExW,HWND,DWORD,const WCHAR*,const WCHAR*,DWORD,int,int,int,int,HWND,HMENU,HINSTANCE,LPVOID);
IN(DefWindowProcW,LRESULT,HWND,UINT,WPARAM,LPARAM);
IN(DestroyWindow,BOOL,HWND);
IN(FindWindowW,HWND,const WCHAR*,const WCHAR*);
IN(PostMessageW,BOOL,HWND,UINT,WPARAM,LPARAM);
IN(GetMessageW,BOOL,MSG*,HWND,UINT,UINT);
IN(TranslateMessage,BOOL,const MSG*);
IN(DispatchMessageW,LRESULT,const MSG*);
IN(PostQuitMessage,void,int);
IN(LoadImageW,HANDLE,HINSTANCE,const WCHAR*,UINT,int,int,UINT);
IN(MessageBoxW,int,HWND,const WCHAR*,const WCHAR*,UINT);
IN(CreatePopupMenu,HMENU,void);
IN(AppendMenuW,BOOL,HMENU,UINT,ULONG_PTR,const WCHAR*);
IN(TrackPopupMenu,BOOL,HMENU,UINT,int,int,int,HWND,const void*);
IN(DestroyMenu,BOOL,HMENU);
IN(SetForegroundWindow,BOOL,HWND);
IN(GetCursorPos,BOOL,POINT*);
IN(OpenClipboard,BOOL,HWND);
IN(EmptyClipboard,BOOL,void);
IN(SetClipboardData,HANDLE,UINT,HANDLE);
IN(CloseClipboard,BOOL,void);
IN(Shell_NotifyIconW,BOOL,DWORD,NOTIFYICONDATAW*);
IN(ShellExecuteW,HINSTANCE,HWND,const WCHAR*,const WCHAR*,const WCHAR*,const WCHAR*,int);
IN(WSAStartup,int,WORD,void*);
IN(WSACleanup,int,void);
IN(socket,SOCKET,int,int,int);
IN(bind,int,SOCKET,const void*,int);
IN(listen,int,SOCKET,int);
IN(accept,SOCKET,SOCKET,void*,int*);
IN(closesocket,int,SOCKET);
IN(shutdown,int,SOCKET,int);
IN(setsockopt,int,SOCKET,int,int,const char*,int);
IN(send,int,SOCKET,const char*,int,int);
IN(recv,int,SOCKET,char*,int,int);

#define INVALID_SOCK (~(SOCKET)0)
#define INVALID_H ((HANDLE)(intptr_t)-1)
#define HFILE_READ 0x80000000u
#define FILE_SHARE_READ 1u
#define OPEN_EXISTING 3u
#define FILE_FLAG_BACKUP_SEMANTICS 0x02000000u
#define FILE_ATTRIBUTE_DIRECTORY 0x10u
#define FILE_ATTR_MISSING 0xffffffffu
#define PORT_FIRST 8765
#define PORT_LIMIT 8784
#define WM_APP 0x8000u
#define WM_USER_TRAY (WM_APP+1)
#define WM_USER_OPEN (WM_APP+2)
#define WM_RBUTTONUP 0x0205u
#define WM_LBUTTONDBLCLK 0x0203u
#define WM_CONTEXTMENU 0x007bu
#define WM_COMMAND 0x0111u
#define WM_DESTROY 0x0002u
#define NIM_ADD 0u
#define NIM_DELETE 2u
#define NIM_SETVERSION 4u
#define NIF_MESSAGE 1u
#define NIF_ICON 2u
#define NIF_TIP 4u
#define NOTIFYICON_VERSION_4 4u
#define MF_STRING 0u
#define MF_SEPARATOR 0x800u
#define TPM_RIGHTBUTTON 2u
#define TPM_BOTTOMALIGN 0x20u
#define CF_UNICODETEXT 13u
#define GMEM_MOVEABLE 2u
#define IMAGE_ICON 1u
#define LR_DEFAULTSIZE 0x40u
#define MSG_INFO 0x40u
#define MSG_ERROR 0x10u
#define CP_UTF8 65001u
#define MB_ERR_INVALID_CHARS 8u
#define MAX_PATHS 32768
#define WIN_ERROR_ALREADY_EXISTS 183u
#define CMD_OPEN 100u
#define CMD_COPY 101u
#define CMD_EXIT 102u
#define CSTR_EQUAL 2

static const WCHAR W_CLASS[] = L"SigmaExplorerTrayWindowNative";
static WCHAR g_class[160], g_mutex_name[160];
static const WCHAR W_TITLE[] = L"SIGMA Explorer";
static WCHAR g_root[MAX_PATHS];
static WCHAR g_canonical[MAX_PATHS];
static WCHAR g_url[128];
static int g_root_len, g_canonical_len, g_port, g_running;
static SOCKET g_listener=INVALID_SOCK;
static HWND g_hwnd;
static HICON g_icon;
static HANDLE g_worker, g_mutex;
static int g_wsa_ok, g_tray_added;
static NOTIFYICONDATAW g_nid;

static size_t wslen(const WCHAR *s){size_t i=0;while(s[i])i++;return i;}
static void copyw(WCHAR *dst,const WCHAR *src,size_t n){size_t i=0;while(i+1<n&&src[i]){dst[i]=src[i];i++;}dst[i]=0;}
static void appendw(WCHAR *dst,const WCHAR *src,size_t cap){size_t j=wslen(dst),i=0;while(j+1<cap && src[i])dst[j++]=src[i++];dst[j]=0;}
static void appnumw(WCHAR *dst,unsigned n){WCHAR tmp[16];int i=0;do{tmp[i++]=(WCHAR)('0'+n%10);n/=10;}while(n);int k=(int)wslen(dst);while(i)dst[k++]=tmp[--i];dst[k]=0;}
/* One tray instance per Explorer directory: opening a second area must not
   silently redirect to the first area's map. The 64-bit path hash forms
   both the mutex and invisible window class names. */
static void init_identity(void){
 uint64_t h=UINT64_C(14695981039346656037);
 for(int i=0;g_canonical[i];i++){
  WCHAR c=g_canonical[i];if(c>='A'&&c<='Z')c=(WCHAR)(c+32);
  h^=(uint64_t)c;h*=UINT64_C(1099511628211);
 }
 const WCHAR digits[]=L"0123456789abcdef";
 copyw(g_class,W_CLASS,160);appendw(g_class,L"_",160);
 for(int shift=60;shift>=0;shift-=4){WCHAR t[2]={digits[(h>>shift)&15],0};appendw(g_class,t,160);}
 copyw(g_mutex_name,L"Local\\SIGMA_Explorer_Native_",160);
 for(int shift=60;shift>=0;shift-=4){WCHAR t[2]={digits[(h>>shift)&15],0};appendw(g_mutex_name,t,160);}
}
static int prefix_case_equal(const WCHAR *a,const WCHAR *b,int n){return CompareStringOrdinal(a,n,b,n,1)==CSTR_EQUAL;}
static char lc(char c){return c>='A' && c<='Z' ? (char)(c+32):c;}
static int match_ci(const char *p,const char *word){while(*word){if(lc(*p++)!=lc(*word++))return 0;}return 1;}
static int send_all(SOCKET s,const char *p,int len){while(len>0){int w=send(s,p,len>16384?16384:len,0);if(w<=0)return 0;p+=w;len-=w;}return 1;}
static void appendtxt(char *dst,int *len,const char *src,int cap){while(*src&&*len+1<cap)dst[(*len)++]=*src++;dst[*len]=0;}
static void appendnum(char *dst,int *len,uint64_t n,int cap){char tmp[32];int k=0;do{tmp[k++]=(char)('0'+n%10);n/=10;}while(n&&k<31);while(k && *len+1<cap)dst[(*len)++]=tmp[--k];dst[*len]=0;}
static int ascii_eq(const char *a,const char *b){while(*a&&*b){if(lc(*a++)!=lc(*b++))return 0;}return *a==*b;}
static const char* mimetype(const char* path){
 const char *dot=0;for(const char*p=path;*p;p++){if(*p=='.')dot=p;}
 if(!dot)return "application/octet-stream";
 if(ascii_eq(dot,".html")||ascii_eq(dot,".htm"))return "text/html; charset=utf-8";
 if(ascii_eq(dot,".js")||ascii_eq(dot,".mjs"))return "text/javascript; charset=utf-8";
 if(ascii_eq(dot,".css"))return "text/css; charset=utf-8";
 if(ascii_eq(dot,".json"))return "application/json";
 if(ascii_eq(dot,".geojson"))return "application/geo+json";
 if(ascii_eq(dot,".png"))return "image/png";
 if(ascii_eq(dot,".svg"))return "image/svg+xml";
 if(ascii_eq(dot,".jpg")||ascii_eq(dot,".jpeg"))return "image/jpeg";
 if(ascii_eq(dot,".webp"))return "image/webp";
 if(ascii_eq(dot,".ico"))return "image/x-icon";
 if(ascii_eq(dot,".wasm"))return "application/wasm";
 if(ascii_eq(dot,".woff2"))return "font/woff2";
 if(ascii_eq(dot,".woff"))return "font/woff";
 if(ascii_eq(dot,".ttf"))return "font/ttf";
 if(ascii_eq(dot,".pbf")||ascii_eq(dot,".mvt")||ascii_eq(dot,".bin"))return "application/octet-stream";
 if(ascii_eq(dot,".txt"))return "text/plain; charset=utf-8";
 return "application/octet-stream";
}
static void send_header(SOCKET s,int status,const char*type,uint64_t length,int head,int partial,uint64_t from,uint64_t to,uint64_t total){
 char h[1024]={0};int k=0;
 appendtxt(h,&k,status==200?"HTTP/1.1 200 OK\r\n":status==206?"HTTP/1.1 206 Partial Content\r\n":status==404?"HTTP/1.1 404 Not Found\r\n":status==405?"HTTP/1.1 405 Method Not Allowed\r\n":status==416?"HTTP/1.1 416 Range Not Satisfiable\r\n":status==403?"HTTP/1.1 403 Forbidden\r\n":"HTTP/1.1 400 Bad Request\r\n",1024);
 appendtxt(h,&k,"Content-Type: ",1024);appendtxt(h,&k,type,1024);appendtxt(h,&k,"\r\nContent-Length: ",1024);appendnum(h,&k,length,1024);
 appendtxt(h,&k,"\r\nConnection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\nAccept-Ranges: bytes\r\n",1024);
 if(partial){appendtxt(h,&k,"Content-Range: bytes ",1024);appendnum(h,&k,from,1024);appendtxt(h,&k,"-",1024);appendnum(h,&k,to,1024);appendtxt(h,&k,"/",1024);appendnum(h,&k,total,1024);appendtxt(h,&k,"\r\n",1024);}
 appendtxt(h,&k,"\r\n",1024);(void)head;send_all(s,h,k);
}
static void simple_error(SOCKET s,int status,int head){static const char body[]="SIGMA Explorer: requested resource not available.\n";send_header(s,status,"text/plain; charset=utf-8",sizeof(body)-1,head,0,0,0,0);if(!head)send_all(s,body,sizeof(body)-1);}
/* Reject DNS-rebinding/foreign-host requests: this service is for a local tab only. */
static int host_allowed(const char *req,int used){
 char h1[64]={0},h2[64]={0};int k=0;appendtxt(h1,&k,"localhost:",64);appendnum(h1,&k,(unsigned)g_port,64);
 k=0;appendtxt(h2,&k,"127.0.0.1:",64);appendnum(h2,&k,(unsigned)g_port,64);
 int pos=0,hosts=0,matched=0;
 while(pos+1<used&&!(req[pos]=='\r'&&req[pos+1]=='\n'))pos++;
 if(pos+1>=used)return 0;
 pos+=2;
 while(pos+1<used){
  int start=pos;
  while(pos+1<used&&!(req[pos]=='\r'&&req[pos+1]=='\n'))pos++;
  if(pos+1>=used)return 0;
  if(pos==start)break;
  if(pos-start>=5&&match_ci(req+start,"Host:")){
   hosts++;
   int from=start+5;while(from<pos&&(req[from]==' '||req[from]=='\t'))from++;
   int to=pos;while(to>from&&(req[to-1]==' '||req[to-1]=='\t'))to--;
   char host[128];int n=to-from;if(n<=0||n>=128)return 0;
   for(int i=0;i<n;i++)host[i]=req[from+i];
   host[n]=0;
   if(ascii_eq(host,h1)||ascii_eq(host,h2))matched=1;
  }
  pos+=2;
 }
 return hosts==1 && matched;
}
static int hex(char c){if(c>='0'&&c<='9')return c-'0';c=lc(c);if(c>='a'&&c<='f')return c-'a'+10;return -1;}
static int safe_path(const char *url,WCHAR* out,int cap,char *decoded,int dcap){
 int j=0,k=0, segstart=0;const char *p=url;
 if(*p!='/')return 0;
 p++;
 while(*p && *p!='?' && *p!='#'){
  unsigned char c=(unsigned char)*p++;
  if(c=='%'){if(!p[0]||!p[1])return 0;int a=hex(*p++),b=hex(*p++);if(a<0||b<0)return 0;c=(unsigned char)(a*16+b);}
  if(c==0||c=='\\'||c==':'||c<32||c==127||j+2>=dcap)return 0;
  if(c=='/'){
   int n=j-segstart;
   if((n==1 && decoded[segstart]=='.')||(n==2 && decoded[segstart]=='.' && decoded[segstart+1]=='.'))return 0;
   segstart=j+1;
  }
  decoded[j++]=(char)c;
 }
 if(j==0){ const char *x="index.html";while(*x)decoded[j++]=*x++; }
 else if(decoded[j-1]=='/')return 0;
 int n=j-segstart;
 if((n==1&&decoded[segstart]=='.')||(n==2&&decoded[segstart]=='.'&&decoded[segstart+1]=='.'))return 0;
 decoded[j]=0;
 k=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,decoded,j,out,cap-1);
 if(k<=0)return 0;
 out[k]=0;
 for(int i=0;i<k;i++)if(out[i]=='/')out[i]='\\';
 return 1;
}
static uint64_t parse_decimal(const char*p,const char**end){uint64_t v=0;int found=0;while(*p>='0'&&*p<='9'){unsigned dig=(unsigned)(*p-'0');if(v>((~(uint64_t)0)-dig)/10){*end=p;return ~(uint64_t)0;}v=v*10+dig;p++;found=1;}*end=p;return found?v:~(uint64_t)0;}
static void serve_file(SOCKET s,HANDLE f,const char *mime,int head,uint64_t start,uint64_t count,int status,uint64_t total){
 if(status==206)send_header(s,206,mime,count,head,1,start,start+count-1,total);
 else send_header(s,200,mime,count,head,0,0,0,0);
 if(head)return;
 if(start>0 && !SetFilePointerEx(f,(int64_t)start,0,0))return;
 char buffer[32768];
 while(count){DWORD got=0;DWORD n=(DWORD)(count>sizeof(buffer)?sizeof(buffer):count);if(!ReadFile(f,buffer,n,&got,0)||!got)break;if(!send_all(s,buffer,(int)got))break;count-=got;}
}
static DWORD __stdcall client_proc(LPVOID param){
 SOCKET s=(SOCKET)(uintptr_t)param;
 DWORD timeout=12000;setsockopt(s,0xffff,0x1006,(const char*)&timeout,4);setsockopt(s,0xffff,0x1005,(const char*)&timeout,4);
 char req[8193];int used=0,done=0;
 while(used<8192){int n=recv(s,req+used,8192-used,0);if(n<=0)break;used+=n;req[used]=0;
  for(int i=3;i<used;i++){if(req[i-3]=='\r'&&req[i-2]=='\n'&&req[i-1]=='\r'&&req[i]=='\n'){done=1;break;}}
  if(done)break;
 }
 if(!done){simple_error(s,400,0);closesocket(s);return 0;}
 if(!host_allowed(req,used)){simple_error(s,403,0);closesocket(s);return 0;}
 int head=0,pos=0;
 if(req[0]=='G'&&req[1]=='E'&&req[2]=='T'&&req[3]==' '){pos=4;}
 else if(req[0]=='H'&&req[1]=='E'&&req[2]=='A'&&req[3]=='D'&&req[4]==' '){head=1;pos=5;}
 else{simple_error(s,405,0);closesocket(s);return 0;}
 int pathstart=pos;while(pos<used&&req[pos]!=' '&&req[pos]!='\r'&&pos-pathstart<4096)pos++;
 if(pos>=used||req[pos]!=' '){simple_error(s,400,head);closesocket(s);return 0;}
 char urlpart[4097];int plen=pos-pathstart;for(int i=0;i<plen;i++)urlpart[i]=req[pathstart+i];urlpart[plen]=0;
 WCHAR rel[4096];char relutf8[4097];
 if(!safe_path(urlpart,rel,4096,relutf8,4097)){simple_error(s,403,head);closesocket(s);return 0;}
 WCHAR full[MAX_PATHS];copyw(full,g_root,MAX_PATHS);appendw(full,rel,MAX_PATHS);
 if(wslen(full)>=MAX_PATHS-1){simple_error(s,400,head);closesocket(s);return 0;}
 HANDLE file=CreateFileW(full,HFILE_READ,FILE_SHARE_READ,0,OPEN_EXISTING,0,0);
 if(file==INVALID_H){
  if(ascii_eq(relutf8,"about.html")){
   static const char about[]="<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>About SIGMA</title><style>body{font:16px/1.65 system-ui;margin:3em auto;max-width:760px;padding:0 1em;color:#202b31}a{color:#9a191e}</style><h1>SIGMA Explorer</h1><p>SIGMA — Spatial Intelligence and Graph Modeling for Acquisition.</p><p>This locally hosted Explorer displays exported SIGMA spatial-economic data. No analytical pipeline is running.</p><p>For the full About page, refresh or republish the Explorer using the SIGMA project tools.</p><p><a href=\"/\">Return to Explorer</a></p></html>";
   send_header(s,200,"text/html; charset=utf-8",sizeof(about)-1,head,0,0,0,0);if(!head)send_all(s,about,sizeof(about)-1);
  } else simple_error(s,404,head);
  closesocket(s);return 0;
 }
 WCHAR final[MAX_PATHS];DWORD fn=GetFinalPathNameByHandleW(file,final,MAX_PATHS,0);
 if(!fn||fn>=MAX_PATHS||fn<=(DWORD)g_canonical_len || !prefix_case_equal(g_canonical,final,g_canonical_len) || final[g_canonical_len]!='\\'){
  simple_error(s,403,head);CloseHandle(file);closesocket(s);return 0;
 }
 int64_t flen=0;if(!GetFileSizeEx(file,&flen)||flen<0){simple_error(s,400,head);CloseHandle(file);closesocket(s);return 0;}
 uint64_t total=(uint64_t)flen,start=0,end=total?total-1:0;
 int partial=0;
 /* RFC 7233: support one forward byte range for map binary viewers. */
 for(int i=0;i+7<used;i++){
  if((i==0||req[i-1]=='\n')&&match_ci(req+i,"Range:")){
   int t=i+6;while(req[t]==' '||req[t]=='\t')t++;
   if(!match_ci(req+t,"bytes="))break;t+=6;
   const char *aft;start=parse_decimal(req+t,&aft);if(start==~(uint64_t)0||*aft!='-'){simple_error(s,416,head);CloseHandle(file);closesocket(s);return 0;}
   t=(int)(aft-req)+1;
   if(req[t]>='0'&&req[t]<='9'){end=parse_decimal(req+t,&aft);if(end==~(uint64_t)0){simple_error(s,416,head);CloseHandle(file);closesocket(s);return 0;}}
   if(start>=total||end<start){simple_error(s,416,head);CloseHandle(file);closesocket(s);return 0;}
   if(end>=total)end=total-1;
   partial=1;break;
  }
 }
 uint64_t count=total?end-start+1:0;
 serve_file(s,file,mimetype(relutf8),head,start,count,partial?206:200,total);
 CloseHandle(file);closesocket(s);return 0;
}
static DWORD __stdcall server_proc(LPVOID unused){(void)unused;while(g_running){SOCKET s=accept(g_listener,0,0);if(s==INVALID_SOCK){if(!g_running)break;continue;}
 if(!g_running){closesocket(s);break;}
 HANDLE th=CreateThread(0,0,client_proc,(LPVOID)(uintptr_t)s,0,0);
 if(!th)closesocket(s);else CloseHandle(th);
 }return 0;}
static void server_stop(void){g_running=0;if(g_listener!=INVALID_SOCK){closesocket(g_listener);g_listener=INVALID_SOCK;}
 if(g_worker){WaitForSingleObject(g_worker,1500);CloseHandle(g_worker);g_worker=0;}
 if(g_wsa_ok){WSACleanup();g_wsa_ok=0;}}
static int init_root(void){
 WCHAR app[MAX_PATHS];DWORD n=GetModuleFileNameW(0,app,MAX_PATHS);
 if(!n||n>=MAX_PATHS-32)return 0;
 int cut=-1;for(int i=0;i<(int)n;i++)if(app[i]=='\\'||app[i]=='/')cut=i;
 if(cut<0)return 0;app[cut+1]=0;
 copyw(g_root,app,MAX_PATHS);
 WCHAR idx[MAX_PATHS];copyw(idx,g_root,MAX_PATHS);appendw(idx,L"index.html",MAX_PATHS);
 if(GetFileAttributesW(idx)==FILE_ATTR_MISSING)return 0;
 WCHAR marker[MAX_PATHS];copyw(marker,g_root,MAX_PATHS);appendw(marker,L".sigma-explorer",MAX_PATHS);
 if(GetFileAttributesW(marker)==FILE_ATTR_MISSING)return 0;
 HANDLE dir=CreateFileW(g_root,HFILE_READ,FILE_SHARE_READ,0,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS,0);
 if(dir==INVALID_H)return 0;
 DWORD got=GetFinalPathNameByHandleW(dir,g_canonical,MAX_PATHS,0);CloseHandle(dir);
 if(!got||got>=MAX_PATHS)return 0;
 g_canonical_len=(int)got;while(g_canonical_len>0&&g_canonical[g_canonical_len-1]=='\\'){g_canonical[--g_canonical_len]=0;}
 g_root_len=(int)wslen(g_root);return 1;
}
static int init_server(void){
 _Alignas(16) BYTE wsa[1024];for(int i=0;i<1024;i++)wsa[i]=0;
 if(WSAStartup(0x0202,wsa)!=0)return 0;g_wsa_ok=1;
 for(int port=PORT_FIRST;port<=PORT_LIMIT;port++){
  SOCKET s=socket(2,1,6);if(s==INVALID_SOCK)return 0;
  SOCKADDR_IN addr={0};addr.sin_family=2;addr.sin_addr=0x0100007f;addr.sin_port=(uint16_t)(((unsigned)port<<8)|((unsigned)port>>8));
  if(bind(s,&addr,sizeof(addr))==0 && listen(s,64)==0){g_listener=s;g_port=port;break;}
  closesocket(s);
 }
 if(g_listener==INVALID_SOCK)return 0;
 g_url[0]=0;appendw(g_url,L"http://localhost:",128);appnumw(g_url,(unsigned)g_port);appendw(g_url,L"/",128);
 g_running=1;return 1;
}
static int open_browser(void){HINSTANCE h=ShellExecuteW(0,L"open",g_url,0,0,1);return (uintptr_t)h>32;}
static void copy_link(void){size_t n=wslen(g_url)+1;HANDLE mem=GlobalAlloc(GMEM_MOVEABLE,n*sizeof(WCHAR));if(!mem)return;
 WCHAR *p=(WCHAR*)GlobalLock(mem);if(!p){GlobalFree(mem);return;}
 for(size_t i=0;i<n;i++)p[i]=g_url[i];GlobalUnlock(mem);
 if(!OpenClipboard(g_hwnd)){GlobalFree(mem);return;}EmptyClipboard();
 if(!SetClipboardData(CF_UNICODETEXT,mem))GlobalFree(mem);CloseClipboard();
}
static void tray_menu(HWND hwnd){POINT p={0};if(!GetCursorPos(&p))return;HMENU menu=CreatePopupMenu();if(!menu)return;
 AppendMenuW(menu,MF_STRING,CMD_OPEN,L"Open Explorer");
 AppendMenuW(menu,MF_STRING,CMD_COPY,L"Copy Local Link");
 AppendMenuW(menu,MF_SEPARATOR,0,0);
 AppendMenuW(menu,MF_STRING,CMD_EXIT,L"Exit SIGMA");
 SetForegroundWindow(hwnd);TrackPopupMenu(menu,TPM_RIGHTBUTTON|TPM_BOTTOMALIGN,(int)p.x,(int)p.y,0,hwnd,0);DestroyMenu(menu);
 PostMessageW(hwnd,0,0,0);
}
static LRESULT __stdcall window_proc(HWND hwnd,UINT msg,WPARAM w,LPARAM l){
 switch(msg){
 case WM_USER_OPEN:open_browser();return 0;
 case WM_USER_TRAY:
  if(((UINT)l&0xffffu)==WM_LBUTTONDBLCLK){open_browser();return 0;}
  if(((UINT)l&0xffffu)==WM_RBUTTONUP||((UINT)l&0xffffu)==WM_CONTEXTMENU){tray_menu(hwnd);return 0;}
  return 0;
 case WM_COMMAND:
  if(((UINT)w&0xffffu)==CMD_OPEN)open_browser();
  else if(((UINT)w&0xffffu)==CMD_COPY)copy_link();
  else if(((UINT)w&0xffffu)==CMD_EXIT)DestroyWindow(hwnd);
  return 0;
 case WM_DESTROY:
  if(g_tray_added){Shell_NotifyIconW(NIM_DELETE,&g_nid);g_tray_added=0;}
  server_stop();PostQuitMessage(0);return 0;
 default:return DefWindowProcW(hwnd,msg,w,l);
 }
}
static int install_tray(HINSTANCE inst){
 g_icon=(HICON)LoadImageW(inst,(const WCHAR*)(uintptr_t)1,IMAGE_ICON,0,0,LR_DEFAULTSIZE);
 if(!g_icon)return 0; // an embedded SIGMA icon is mandatory
 WNDCLASSW wc={0};wc.lpfnWndProc=window_proc;wc.hInstance=inst;wc.lpszClassName=g_class;wc.hIcon=g_icon;
 if(!RegisterClassW(&wc))return 0;
 g_hwnd=CreateWindowExW(0,g_class,W_TITLE,0,0,0,0,0,0,0,inst,0);
 if(!g_hwnd)return 0;
 g_nid.cbSize=sizeof(g_nid);g_nid.hWnd=g_hwnd;g_nid.uID=1;g_nid.uFlags=NIF_ICON|NIF_MESSAGE|NIF_TIP;g_nid.uCallbackMessage=WM_USER_TRAY;g_nid.hIcon=g_icon;
 copyw(g_nid.szTip,L"SIGMA Explorer — right-click to exit",128);
 if(!Shell_NotifyIconW(NIM_ADD,&g_nid))return 0;
 g_tray_added=1;g_nid.uTimeout=NOTIFYICON_VERSION_4;Shell_NotifyIconW(NIM_SETVERSION,&g_nid);return 1;
}
void mainCRTStartup(void){
 HINSTANCE inst=GetModuleHandleW(0);
 if(!init_root()){
  MessageBoxW(0,L"Could not find a complete exported Explorer.\n\nPlace sigma.exe INSIDE the exported area-explorer folder containing index.html and .sigma-explorer.",W_TITLE,MSG_ERROR);
  return;
 }
 init_identity();
 g_mutex=CreateMutexW(0,0,g_mutex_name);
 if(!g_mutex){MessageBoxW(0,L"Could not initialize SIGMA Explorer.",W_TITLE,MSG_ERROR);return;}
 if(GetLastError()==WIN_ERROR_ALREADY_EXISTS){
  for(int i=0;i<10;i++){HWND old=FindWindowW(g_class,0);if(old){PostMessageW(old,WM_USER_OPEN,0,0);break;}Sleep(100);}
  CloseHandle(g_mutex);return;
 }
 if(!init_server()){
  MessageBoxW(0,L"Could not start the local SIGMA web server.\nCheck that no other application is using ports 8765-8784.",W_TITLE,MSG_ERROR);
  server_stop();CloseHandle(g_mutex);return;
 }
 if(!install_tray(inst)){
  MessageBoxW(0,L"Could not initialize the SIGMA system tray icon.",W_TITLE,MSG_ERROR);
  if(g_hwnd)DestroyWindow(g_hwnd);else server_stop();
  CloseHandle(g_mutex);return;
 }
 g_worker=CreateThread(0,0,server_proc,0,0,0);
 if(!g_worker){MessageBoxW(0,L"Could not start the SIGMA server thread.",W_TITLE,MSG_ERROR);DestroyWindow(g_hwnd);CloseHandle(g_mutex);return;}
 if(!open_browser()){
  MessageBoxW(0,L"Could not open your default browser. SIGMA is shutting down.",W_TITLE,MSG_ERROR);
  DestroyWindow(g_hwnd);CloseHandle(g_mutex);return;
 }
 MSG msg;while(GetMessageW(&msg,0,0,0)>0){TranslateMessage(&msg);DispatchMessageW(&msg);}
 CloseHandle(g_mutex);
}
