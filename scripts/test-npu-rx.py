#!/usr/bin/env python3
"""Exercise the actual prepared mt76 dequeue with modeled skb/page-pool APIs."""
import ctypes, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
source = Path(sys.argv[1])
text = (source/'npu.c').read_text()
a=text.index('static struct sk_buff *mt76_npu_dequeue('); b=text.index('\nvoid mt76_npu_check_ppe',a)
function=text[a:b]
header=(source/'airoha_offload.h').read_text()
defines='\n'.join(re.findall(r'^#define NPU_RX_DMA_\w+\s+.+$',header,re.M))
prelude=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
typedef uint32_t u32;
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) ((UINT32_MAX>>(31-(h)))&(UINT32_MAX<<(l)))
#define FIELD_GET(m,v) (((v)&(m))>>__builtin_ctz(m))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define max_t(t,a,b) ((t)(a)>(t)(b)?(t)(a):(t)(b))
#define READ_ONCE(x) (x)
#define dma_rmb() do {} while(0)
#define Q_WRITE(q,r,v) do {} while(0)
#define ERR_PTR(n) ((void*)(intptr_t)(n))
#define EIO 5
#define ENOMEM 12
#define MAX_SKB_FRAGS 17
struct page { unsigned id; };
struct skb_shared_info { unsigned nr_frags; struct page *frags[17]; };
struct sk_buff { struct page *head; struct skb_shared_info info; unsigned len; };
struct mt76_queue_entry { void *buf; uintptr_t dma_addr[2]; unsigned dma_len[2]; };
struct mt76_queue { void *desc; struct mt76_queue_entry *entry; int tail,queued,ndesc,buf_size; void *page_pool; };
struct mt76_dev { void *dma_dev; };
struct airoha_npu_rx_dma_desc { u32 ctrl,info,data,addr,host_magic,host_capacity; };
static struct page pages[512];
static unsigned freed[512], syncs, allocations, oom, errors;
static struct sk_buff skb;
static void clear(void *p,size_t n) { unsigned char *b=p; while(n--) *b++=0; }
void *memset(void *p,int v,size_t n) {unsigned char *b=p;while(n--)*b++=v;return p;}
void *memcpy(void *p,const void *s,size_t n) {unsigned char *a=p;const unsigned char *b=s;while(n--)*a++=*b++;return p;}
static void dma_sync_single_for_cpu(void *d,uintptr_t a,unsigned len,int dir) {
 (void)d;(void)len;(void)dir; syncs++; if(freed[a/4096-1]) errors++;
}
static int page_pool_get_dma_dir(void *p) {(void)p;return 2;}
static struct sk_buff *napi_build_skb(void *p,int n) {
 (void)n;allocations++; if(oom)return NULL;clear(&skb,sizeof(skb));skb.head=p;return &skb;
}
static void mt76_put_page_pool_buf(void *p,bool direct) {
 (void)direct;struct page *page=p;if(++freed[page->id]!=1)errors++;
}
static void __skb_put(struct sk_buff *s,int n){s->len+=n;}
static void skb_reset_mac_header(struct sk_buff *s){(void)s;}
static void skb_mark_for_recycle(struct sk_buff *s){(void)s;}
static struct skb_shared_info *skb_shinfo(struct sk_buff *s){return &s->info;}
static struct page *virt_to_head_page(void *p){return p;}
static void *page_address(struct page *p){return p;}
static void skb_add_rx_frag(struct sk_buff *s,int i,struct page *p,size_t off,int len,int size) {
 (void)off;(void)size;s->info.frags[i]=p;s->info.nr_frags=i+1;s->len+=len;
}
'''
tests=r'''
static struct airoha_npu_rx_dma_desc desc[512];
static struct mt76_queue_entry entries[512];
#define CHECK(x) do {if(!(x))return __LINE__;}while(0)
int run_host(unsigned count,unsigned tail,unsigned fault) {
 clear(desc,sizeof(desc));clear(entries,sizeof(entries));clear(freed,sizeof(freed));
 syncs=allocations=errors=oom=0;
 struct mt76_queue q={.desc=desc,.entry=entries,.tail=tail,.queued=count+2,.ndesc=512,.buf_size=2304};
 struct mt76_dev dev={0};u32 info=0;
 for(unsigned i=0;i<512;i++) {pages[i].id=i;entries[i].buf=&pages[i];entries[i].dma_addr[0]=(i+1)*4096;entries[i].dma_len[0]=1920;desc[i].addr=(i+1)*4096;}
 for(unsigned i=0;i<count;i++) {
  unsigned slot=(tail+i)%512;
  desc[slot].ctrl=1|(100<<1)|((count*100)<<15)|((i+1==count)?BIT(29):0);
  desc[slot].info=count>1 ? (count<<29)|((i+1)<<26) : 0;
 }
 unsigned last=(tail+count-1)%512;
 if(fault==1)q.queued=0;
 if(fault==2)desc[last].ctrl&=~1U;
 if(fault==3)q.queued=count-1;
 if(fault==4)entries[last].dma_len[0]=99;
 if(fault==5)desc[last].info^=BIT(26);
 if(fault==6)desc[last].ctrl^=BIT(29);
 if(fault==7)desc[last].ctrl^=BIT(15);
 if(fault==8)oom=1;
 if(fault==9)desc[last].addr++;
 int queued=q.queued;
 struct sk_buff *s=mt76_npu_dequeue(&dev,&q,&info);
 if(!fault || fault==8) {
  CHECK(q.tail==(tail+count)%512 && q.queued==2 && syncs==count && allocations==1);
  CHECK(fault==8 ? s==ERR_PTR(-ENOMEM) : s==&skb);
  if(!fault) {
   CHECK(s->len==count*100 && s->info.nr_frags==count-1);
   mt76_put_page_pool_buf(s->head,false);
   for(unsigned i=0;i<s->info.nr_frags;i++)mt76_put_page_pool_buf(s->info.frags[i],false);
  }
  for(unsigned i=0;i<count;i++) {unsigned k=(tail+i)%512;CHECK(entries[k].buf==NULL && freed[k]==1);}
  CHECK(!freed[(tail+count)%512] && !freed[(tail+count+1)%512]);
 } else {
  CHECK(q.tail==tail && q.queued==queued && syncs==0 && allocations==0);
  CHECK(s==NULL || s==ERR_PTR(-EIO));
  for(unsigned i=0;i<count;i++){unsigned k=(tail+i)%512;CHECK(entries[k].buf==&pages[k] && !freed[k]);}
 }
 CHECK(!errors);return 0;
}
'''
compiler=shutil.which(os.environ.get('CC','clang')); windows=os.name=='nt'
with tempfile.TemporaryDirectory(prefix='mt76-rx-test-') as tmp:
 d=Path(tmp); c=d/'test.c'; c.write_text(prelude+defines+'\n'+function+'\n'+tests)
 obj=d/'test.o'; libpath=d/('test.dll' if windows else 'test.so')
 flags=['-O2','-ffreestanding','-fno-builtin','-Wall','-Wextra']
 flags+=['--target=x86_64-pc-windows-msvc','-mno-stack-arg-probe'] if windows else ['-fPIC']
 subprocess.run([compiler,*flags,'-c',str(c),'-o',str(obj)],check=True)
 if windows:
  cmd=[str(Path(compiler).with_name('lld.exe')),'-flavor','link','/dll','/noentry','/nodefaultlib','/export:run_host','/out:'+str(libpath),str(obj)]
 else:cmd=[compiler,'-shared','-Wl,-Bsymbolic',str(obj),'-o',str(libpath)]
 subprocess.run(cmd,check=True);lib=ctypes.CDLL(str(libpath));lib.run_host.argtypes=[ctypes.c_uint32]*3
 cases=0
 try:
  for count in range(1,8):
   for tail in (0,510,511):
    for fault in range(10):
     if count==1 and fault==5:continue
     line=lib.run_host(count,tail,fault)
     assert line==0,((count,tail,fault),'C assertion line',line)
     cases+=1
  print(f'PASS: {cases} actual mt76 dequeue ownership scenarios')
 finally:
  if windows:ctypes.windll.kernel32.FreeLibrary(ctypes.c_void_p(lib._handle))
