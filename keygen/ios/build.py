# Dựng app iOS (PWA) tạo key — một file HTML tự chứa, không gọi mạng, không chứa khóa bí mật.
import base64, os
D="/tmp/claude-0/pwa"
noble=open(f"{D}/noble.inl.js",encoding="utf8").read()
icon=open("/tmp/claude-0/icon.png","rb").read()
icon_b64=base64.b64encode(icon).decode()

core=r'''
/* ===== Lõi tạo key: GIỐNG HỆT KeyGen trên máy tính (Ed25519, cùng định dạng khóa) ===== */
const B32='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567', te=new TextEncoder();
const hx=h=>Uint8Array.from(h.match(/../g).map(x=>parseInt(x,16)));
const tohex=u=>[...u].map(b=>b.toString(16).padStart(2,'0')).join('');
const b32enc=u=>{let bits=0,val=0,o='';for(const b of u){val=(val*256+b);bits+=8;while(bits>=5){o+=B32[(Math.floor(val/Math.pow(2,bits-5)))&31];bits-=5;val%=Math.pow(2,bits);}}if(bits>0)o+=B32[(val*Math.pow(2,5-bits))&31];return o;};
const b32dec=s=>{s=s.replace(/[^A-Z2-7]/gi,'').toUpperCase();let bits=0,val=0;const o=[];for(const c of s){val=val*32+B32.indexOf(c);bits+=5;if(bits>=8){o.push((Math.floor(val/Math.pow(2,bits-8)))&255);bits-=8;val%=Math.pow(2,bits);}}return Uint8Array.from(o);};
const EPOCH=Date.UTC(2024,0,1);
const dayNum=(d=new Date())=>Math.floor((Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate())-EPOCH)/86400000);
const fmtDate=dn=>{const d=new Date(EPOCH+dn*86400000),p=n=>String(n).padStart(2,'0');return p(d.getUTCDate())+'/'+p(d.getUTCMonth()+1)+'/'+d.getUTCFullYear();};
async function unseal(v,password){
  const salt=hx(v.salt),nonce=hx(v.nonce),data=hx(v.data),iter=v.iter;
  const base=await crypto.subtle.importKey('raw',te.encode(password),'PBKDF2',false,['deriveBits']);
  const bits=await crypto.subtle.deriveBits({name:'PBKDF2',salt,iterations:iter,hash:'SHA-256'},base,256);
  const ak=await crypto.subtle.importKey('raw',bits,'AES-GCM',false,['decrypt']);
  let sb; try{ sb=await crypto.subtle.decrypt({name:'AES-GCM',iv:nonce,tagLength:128},ak,data); }catch(e){ throw new Error('Mật khẩu chưa đúng.'); }
  const seed=new Uint8Array(sb); if(seed.length!==32) throw new Error('Mật khẩu chưa đúng.');
  const pub=await getPublicKeyAsync(seed);
  return {seed,pub:tohex(pub)};
}
async function seal(seed,password){
  const salt=crypto.getRandomValues(new Uint8Array(16)),nonce=crypto.getRandomValues(new Uint8Array(12)),iter=600000;
  const base=await crypto.subtle.importKey('raw',te.encode(password),'PBKDF2',false,['deriveBits']);
  const bits=await crypto.subtle.deriveBits({name:'PBKDF2',salt,iterations:iter,hash:'SHA-256'},base,256);
  const ak=await crypto.subtle.importKey('raw',bits,'AES-GCM',false,['encrypt']);
  const ct=new Uint8Array(await crypto.subtle.encrypt({name:'AES-GCM',iv:nonce,tagLength:128},ak,seed));
  const pub=await getPublicKeyAsync(seed);
  return {app:'MTCC-KeyGen',pub:tohex(pub),salt:tohex(salt),nonce:tohex(nonce),data:tohex(ct),iter};
}
function parseMachine(s){const t=(s||'').replace(/[-\s]/g,'').toUpperCase();if(!/^[A-Z2-7]{13}$/.test(t))throw new Error('Mã máy chưa đúng. Mã có dạng ABCD-EFGH-IJKLM.');const b=b32dec(t);if(b.length!==8)throw new Error('Mã máy chưa đúng. Mã có dạng ABCD-EFGH-IJKLM.');return b;}
async function makeKey(seed,m8,nowDay,days,serial){
  const body=new Uint8Array(14);body[0]=1;body[1]=serial&255;body[2]=(nowDay>>>8)&255;body[3]=nowDay&255;
  let exp=0xFFFF,label='Vĩnh viễn';if(days>0){exp=nowDay+days;label=fmtDate(exp);}
  body[4]=(exp>>>8)&255;body[5]=exp&255;body.set(m8,6);
  const msg=new Uint8Array(19);msg.set(te.encode('MTCC1'),0);msg.set(body,5);
  const sig=await signAsync(msg,seed);
  const all=new Uint8Array(78);all.set(body,0);all.set(sig,14);
  const t=b32enc(all),g=[];for(let i=0;i<t.length;i+=5)g.push(t.slice(i,i+5));
  return {key:'MTCC-'+g.join('-'),label};
}
'''

ui=r'''
/* ===== Giao diện ===== */
const R=document.getElementById('root'); const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const LS={vault:'mtcc_vault',hist:'mtcc_hist'};
let SEED=null, PUB=null, tab='make';
const getVault=()=>{try{return JSON.parse(localStorage.getItem(LS.vault)||'null')}catch(e){return null}};
const setVault=v=>localStorage.setItem(LS.vault,JSON.stringify(v));
const getHist=()=>{try{return JSON.parse(localStorage.getItem(LS.hist)||'[]')}catch(e){return []}};
const setHist=h=>localStorage.setItem(LS.hist,JSON.stringify(h));
const copy=async(t,b)=>{try{await navigator.clipboard.writeText(t);const o=b.textContent;b.textContent='Đã chép';setTimeout(()=>b.textContent=o,1400)}catch(e){b.textContent='Hãy tự chọn rồi chép tay'}};
const now2=()=>{const d=new Date(),p=n=>String(n).padStart(2,'0');return p(d.getDate())+'/'+p(d.getMonth()+1)+'/'+d.getFullYear()+' '+p(d.getHours())+':'+p(d.getMinutes());};
function draw(){const v=getVault();if(!v)return setup();if(!SEED)return lock();shell();}
function setup(){R.innerHTML='<div class=center><div class=card><div class=logo></div><h1>MThanglee KeyGen</h1><p>Lần đầu dùng: hãy <b>khôi phục từ bản sao lưu khóa</b> bạn đã tải từ KeyGen trên máy tính, để iPhone tạo ra đúng key hợp lệ. Nếu tạo bộ khóa mới ở đây, key sẽ KHÁC và bản app đã phát hành sẽ không nhận.</p><label for=bk>Dán nội dung file sao lưu (MThanglee_KeyGen_sao_luu_khoa.json)</label><textarea id=bk placeholder=\'{"app":"MTCC-KeyGen", ...}\'></textarea><div class=row><button id=pick>Chọn file .json</button></div><label for=p1>Mật khẩu của bản sao lưu</label><input id=p1 type=password><div class=err id=e></div><div class=row><button class="pri grow" id=go>Khôi phục khóa</button></div><input id=f type=file accept=.json,application/json hidden><details style="margin-top:14px"><summary>Tạo bộ khóa mới (chỉ khi làm phần mềm mới từ đầu)</summary><p>Việc này sinh một bộ khóa hoàn toàn mới. Sau đó phải dán Khóa công khai vào app và build lại thì key mới có tác dụng.</p><label for=np>Mật khẩu mới, ít nhất 8 ký tự</label><input id=np type=password><div class=row><button id=mk>Tạo bộ khóa mới</button></div></details></div></div>';
 pick.onclick=()=>f.click(); f.onchange=async()=>{if(f.files[0]){bk.value=await f.files[0].text();f.value='';}};
 go.onclick=async()=>{e.textContent='';let v;try{v=JSON.parse(bk.value)}catch(x){e.textContent='Nội dung sao lưu không đúng (phải là file .json).';return}if(!v||v.app!=='MTCC-KeyGen'){e.textContent='File này không phải bản sao lưu khóa.';return}go.disabled=true;go.textContent='Đang mở…';try{const r=await unseal(v,p1.value);SEED=r.seed;PUB=r.pub;setVault(v);draw();}catch(x){e.textContent=x.message;go.disabled=false;go.textContent='Khôi phục khóa';}};
 mk.onclick=async()=>{e.textContent='';if((np.value||'').length<8){e.textContent='Mật khẩu mới cần ít nhất 8 ký tự.';return}mk.disabled=true;try{const seed=crypto.getRandomValues(new Uint8Array(32));const v=await seal(seed,np.value);SEED=seed;const r=await unseal(v,np.value);PUB=r.pub;setVault(v);tab='vault';draw();}catch(x){e.textContent=x.message;mk.disabled=false;}};}
function lock(){R.innerHTML='<div class=center><div class=card><div class=logo></div><h1>MThanglee KeyGen</h1><p>Nhập mật khẩu để mở bộ khóa.</p><form id=fm><label for=p1>Mật khẩu</label><input id=p1 type=password autocomplete=current-password><div class=err id=e></div><div class=row><button class="pri grow" id=go>Mở khóa</button></div></form><details style="margin-top:12px"><summary>Dùng bản sao lưu khác</summary><div class=row style="margin-top:8px"><button id=rs>Khôi phục từ file sao lưu</button></div><p class=warn>Thao tác này thay bộ khóa đang lưu trên máy này.</p></details></div></div>';
 fm.onsubmit=async ev=>{ev.preventDefault();go.disabled=true;e.textContent='';try{const r=await unseal(getVault(),p1.value);SEED=r.seed;PUB=r.pub;draw();}catch(x){e.textContent=x.message;go.disabled=false;}};
 rs.onclick=()=>{localStorage.removeItem(LS.vault);SEED=null;draw();};}
function shell(){R.innerHTML='<header><span class=logo-sm></span><b>MThanglee KeyGen</b><button role=tab data-t=make>Tạo key</button><button role=tab data-t=hist>Lịch sử ('+getHist().length+')</button><button role=tab data-t=vault>Khóa &amp; sao lưu</button><span class=sp></span><button id=lk>Khóa</button></header><main id=m></main>';
 document.querySelectorAll('[data-t]').forEach(b=>{b.setAttribute('aria-selected',b.dataset.t===tab);b.onclick=()=>{tab=b.dataset.t;shell();}});
 lk.onclick=()=>{SEED=null;draw();};({make,hist,vault})[tab]();}
function make(){m.innerHTML='<div class=grid><div class=box><h2>Thông tin khách</h2><label for=n>Tên khách</label><input id=n placeholder="Ví dụ: Studio An Nhiên"><label for=mc>Mã máy khách gửi</label><input id=mc placeholder="ABCD-EFGH-IJKLM" autocapitalize=characters spellcheck=false><label class=check><input type=checkbox id=any> Key dùng cho mọi máy</label><p class=warn id=aw hidden>Key mọi máy có thể chia sẻ cho người khác. Chỉ dùng khi cần.</p><div id=qr hidden><label for=q>Số lượng key</label><input id=q type=number min=1 max=200 value=1></div><label for=d>Thời hạn</label><select id=d><option value=0>Vĩnh viễn</option><option value=30>30 ngày</option><option value=90>90 ngày</option><option value=180>180 ngày</option><option value=365 selected>1 năm</option><option value=730>2 năm</option><option value=-1>Tự nhập số ngày</option></select><div id=dayrow hidden><label for=c>Số ngày</label><input id=c type=number min=1 value=7></div><label for=nt>Ghi chú</label><input id=nt placeholder="Không bắt buộc"><div class=err id=e></div><div class=row><button class="pri grow" id=go>Tạo key</button></div></div><div class=box><h2>Key vừa tạo</h2><div id=out><p>Key sẽ hiện ở đây.</p></div></div></div>';
 any.onchange=()=>{aw.hidden=qr.hidden=!any.checked;mc.disabled=any.checked;};d.onchange=()=>{document.getElementById('dayrow').hidden=(d.value!=='-1');};
 go.onclick=async()=>{e.textContent='';const days=d.value==='-1'?+c.value:+d.value;if(!(days>=0&&days<=18000)){e.textContent='Số ngày chưa đúng.';return}let m8,label;try{if(any.checked){m8=new Uint8Array(8);label='Mọi máy';}else{m8=parseMachine(mc.value);label=mc.value.trim().toUpperCase();}}catch(x){e.textContent=x.message;return}go.disabled=true;go.textContent='Đang tạo…';try{const qty=any.checked?Math.min(200,Math.max(1,+q.value||1)):1;const nd=dayNum();const ks=[];const h=getHist();for(let i=0;i<qty;i++){const r=await makeKey(SEED,m8,nd,days,i);const it={time:now2(),name:(n.value||'').trim(),machine:label,expires:r.label,note:(nt.value||'').trim(),key:r.key};ks.push(it);h.unshift(it);}setHist(h);show(ks);document.querySelector('[data-t=hist]').textContent='Lịch sử ('+h.length+')';}catch(x){e.textContent=x.message;}go.disabled=false;go.textContent='Tạo key';};}
function show(ks){out.innerHTML='<p>'+esc(ks[0].name||'Khách')+' · '+esc(ks[0].machine)+' · Hạn: '+esc(ks[0].expires)+'</p><textarea id=kt readonly aria-label="Key vừa tạo">'+esc(ks.map(k=>k.key).join('\n'))+'</textarea><div class=row><button class=pri id=cp>Sao chép key</button><button id=sh>Chia sẻ</button></div>';cp.onclick=e=>copy(kt.value,e.target);sh.onclick=async()=>{try{await navigator.share({text:kt.value})}catch(e){}};sh.hidden=!navigator.share;}
function hist(){const h=getHist();m.innerHTML='<div class=box><div class=row style="margin:0 0 10px"><input id=s placeholder="Tìm theo tên, mã máy, ghi chú" class=grow style="flex:1;width:auto"><button id=csv>Xuất CSV</button></div><div class=tw><table><thead><tr><th>Ngày tạo</th><th>Khách</th><th>Mã máy</th><th>Hạn</th><th>Ghi chú</th><th>Key</th><th></th></tr></thead><tbody id=tb></tbody></table></div></div>';
 const paint=()=>{const q=s.value.toLowerCase(),l=h.filter(x=>(x.name+x.machine+x.note).toLowerCase().includes(q));tb.innerHTML=l.map(x=>'<tr><td>'+esc(x.time)+'</td><td>'+esc(x.name)+'</td><td>'+esc(x.machine)+'</td><td>'+esc(x.expires)+'</td><td>'+esc(x.note)+'</td><td class=k>'+esc(x.key)+'</td><td><button data-k="'+esc(x.key)+'">Chép</button></td></tr>').join('')||'<tr><td colspan=7>Chưa có key.</td></tr>';tb.querySelectorAll('button').forEach(b=>b.onclick=()=>copy(b.dataset.k,b));};s.oninput=paint;paint();
 csv.onclick=()=>{const q=v=>'"'+String(v||'').replace(/"/g,'""')+'"',t='﻿Ngày tạo,Khách,Mã máy,Hạn,Ghi chú,Key\n'+h.map(x=>[x.time,x.name,x.machine,x.expires,x.note,x.key].map(q).join(',')).join('\n');dl(t,'MThanglee_lich_su_key.csv','text/csv');};}
function dl(text,name,type){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;document.body.appendChild(a);a.click();a.remove();}
function vault(){const v=getVault();m.innerHTML='<div class=grid><div class=box><h2>Khóa công khai</h2><p>Chuỗi này để dán vào app trước khi build (chỉ cần khi làm bộ khóa mới).</p><div class=mono id=pk>'+esc(PUB)+'</div><div class=row><button class=pri id=cp>Sao chép khóa công khai</button></div></div><div class=box><h2>Sao lưu khóa bí mật</h2><p>File đã mã hóa bằng mật khẩu của bạn. Cất ở nơi an toàn. Trên iPhone, dữ liệu app có thể bị xóa khi máy thiếu bộ nhớ — hãy giữ sẵn bản sao lưu này.</p><div class=row><button class=pri id=bk>Lưu / chia sẻ file sao lưu</button><button id=cpb>Chép nội dung</button></div><p class=warn style="margin-top:12px">Không gửi file này hay mật khẩu cho ai. Không đưa lên mạng.</p></div></div>';
 cp.onclick=e=>copy(PUB,e.target);const vj=JSON.stringify(v,null,1);cpb.onclick=e=>copy(vj,e.target);
 bk.onclick=async()=>{if(navigator.share&&navigator.canShare){try{const file=new File([vj],'MThanglee_KeyGen_sao_luu_khoa.json',{type:'application/json'});if(navigator.canShare({files:[file]})){await navigator.share({files:[file]});return;}}catch(e){}}dl(vj,'MThanglee_KeyGen_sao_luu_khoa.json','application/json');};}
addEventListener('DOMContentLoaded',draw); if(document.readyState!=='loading')draw();
'''

html = '''<!doctype html><html lang="vi"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="google" content="notranslate"><meta name="format-detection" content="telephone=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="KeyGen">
<meta name="theme-color" content="#10141b">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icon-180.png">
<title>MThanglee KeyGen</title>
<style>
:root{--bg:#10141b;--panel:#191f29;--panel2:#232b38;--line:#333e4e;--fg:#edf1f6;--mut:#9fabba;--acc:#ffa31a;--on:#241200;--bad:#ff9d9b;--good:#7ddc9c}
*{box-sizing:border-box}html,body{min-height:100%;margin:0}body{background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,"Segoe UI",system-ui,sans-serif;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);-webkit-text-size-adjust:100%}
button,input,select,textarea{font:inherit;color:inherit}button{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:10px 15px;cursor:pointer;-webkit-appearance:none}button:hover{border-color:var(--acc)}button.pri{background:var(--acc);border-color:var(--acc);color:var(--on);font-weight:700}button:disabled{opacity:.6}
input,select,textarea{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:11px 12px;width:100%;min-width:0;-webkit-appearance:none}textarea{font:12.5px ui-monospace,Menlo,Consolas,monospace;min-height:92px;resize:vertical}
:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.center{min-height:100vh;display:grid;place-items:center;padding:16px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px;width:min(460px,100%)}
h1{font-size:21px;margin:6px 0 4px}h2{font-size:16px;margin:0 0 10px}p{color:var(--mut);margin:4px 0 12px;font-size:14px}label{display:block;font-size:13px;color:var(--mut);margin:12px 0 4px}summary{cursor:pointer;color:var(--acc);font-size:13.5px}
.err{color:var(--bad);min-height:20px;font-size:13.5px;margin-top:8px}.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.grow{flex:1}
header{display:flex;align-items:center;gap:8px;padding:10px 14px;background:var(--panel);border-bottom:1px solid var(--line);flex-wrap:wrap;position:sticky;top:0;z-index:2}header b{margin-right:10px;font-size:15px}header button{border-color:transparent;background:none;color:var(--mut);padding:8px 8px}header button[aria-selected=true]{color:var(--fg);box-shadow:inset 0 -2px 0 var(--acc);border-radius:0}.sp{flex:1}
main{padding:16px;max-width:980px;margin:0 auto}.grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}@media(max-width:760px){.grid{grid-template-columns:minmax(0,1fr)}}.box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;min-width:0}
.check{display:flex;gap:8px;align-items:center;color:var(--fg);font-size:14px;margin-top:12px}.check input{width:18px;height:18px;accent-color:var(--acc)}
.warn{color:#ffcf8a;font-size:13px}.mono{font:12.5px ui-monospace,Menlo,Consolas,monospace;word-break:break-all;background:var(--panel2);padding:9px;border-radius:8px;border:1px solid var(--line)}
.tw{overflow:auto;-webkit-overflow-scrolling:touch}table{border-collapse:collapse;width:100%;font-size:13px}th{color:var(--mut);text-align:left;font-weight:600}td,th{padding:8px;border-bottom:1px solid var(--line);white-space:nowrap}td.k{max-width:150px;overflow:hidden;text-overflow:ellipsis;font-family:ui-monospace,Menlo,monospace;font-size:12px}
ol{margin:6px 0 0;padding-left:20px;color:var(--mut);font-size:13.5px}
.logo{width:56px;height:56px;border-radius:14px;background:#141518;border:1px solid #3a3222;display:grid;place-items:center;margin-bottom:6px}
.logo::after,.logo-sm::after{content:"M";font-weight:800;color:var(--acc);font-family:Georgia,serif}.logo::after{font-size:32px}
.logo-sm{width:26px;height:26px;border-radius:7px;background:#141518;display:inline-grid;place-items:center;vertical-align:middle}.logo-sm::after{font-size:16px}
</style></head><body><div id="root"></div>
<script type="module">
/*NOBLE*/
/*CORE*/
/*UI*/
</script></body></html>'''

html=html.replace('/*NOBLE*/',noble).replace('/*CORE*/',core).replace('/*UI*/',ui)
open(f"{D}/index.html","w",encoding="utf8").write(html)

man='''{"name":"MThanglee KeyGen","short_name":"KeyGen","lang":"vi","start_url":"./index.html","scope":"./","display":"standalone","orientation":"any","background_color":"#10141b","theme_color":"#10141b","icons":[{"src":"icon-192.png","sizes":"192x192","type":"image/png"},{"src":"icon-512.png","sizes":"512x512","type":"image/png"},{"src":"icon-512.png","sizes":"512x512","type":"image/png","purpose":"maskable"}]}'''
open(f"{D}/manifest.webmanifest","w").write(man)

# icons from the gold-M png (resize)
from PIL import Image
im=Image.open("/tmp/claude-0/icon.png").convert("RGBA")
for sz in (180,192,512):
    im.resize((sz,sz),Image.LANCZOS).save(f"{D}/icon-{sz}.png")

# simple offline service worker
sw='''const C="mtcc-keygen-v2",F=["./","./index.html","./manifest.webmanifest","./icon-180.png","./icon-192.png","./icon-512.png"];
self.addEventListener("install",e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(F)).then(()=>self.skipWaiting()))});
self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
self.addEventListener("fetch",e=>{if(e.request.method!=="GET")return;e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)))});'''
open(f"{D}/sw.js","w").write(sw)
# register SW in page
h=open(f"{D}/index.html",encoding="utf8").read()
h=h.replace('</body>','<script>if("serviceWorker"in navigator){addEventListener("load",()=>navigator.serviceWorker.register("sw.js").catch(()=>{}))}</script></body>')
open(f"{D}/index.html","w",encoding="utf8").write(h)
print("built", os.path.getsize(f"{D}/index.html"),"bytes html; files:", sorted(os.listdir(D)))
