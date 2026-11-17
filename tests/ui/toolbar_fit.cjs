// Thanh công cụ không bị cắt ở các độ rộng màn hình thường gặp (node tests/ui/toolbar_fit.cjs [thư_mục_ảnh_chụp])
// Hai trạng thái: chưa có đề xuất / có đề xuất + có ảnh đã loại (hiện thêm Khôi phục, ✦ ★1, Bỏ đề xuất).
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert');
const html=fs.readFileSync(path.join(__dirname,'../../app/photosift/web/index.html'),'utf8');
const shots=process.argv[2]||'';
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
const mk=(id,busy)=>({id,name:`MT_${String(id).padStart(4,'0')}.JPG`,dir:'/s',cam:'X',taken:id,w:64,h:48,rating:busy&&id===5?-1:0,label:null,grp:0,best:0,score:50,sharp:1,fsharp:1,nf:0,people:[],flags:[],an:true,err:false,smile:-1,tv:1,sugg:busy&&id<4?1:0});
(async()=>{const b=await chromium.launch();const errs=[];
for(const w of [1280,1366,1440,1536,1600,1920])for(const busy of [false,true]){
  const pg=await b.newPage({viewport:{width:w,height:800},deviceScaleFactor:1});pg.on('pageerror',e=>errs.push(e.message));
  await pg.route('**/*',r=>{const p=new URL(r.request().url()).pathname,J=o=>r.fulfill({body:JSON.stringify(o),contentType:'application/json'});
    if(p==='/')return r.fulfill({body:html,contentType:'text/html'});
    if(p.startsWith('/thumb/'))return r.fulfill({body:png,contentType:'image/png'});
    if(p==='/api/photos')return J(Array.from({length:20},(_,i)=>mk(i+1,busy)));
    if(p==='/api/status')return J({state:'done',root:'/s',online:true,eyes:true,total:20,done:20,thumbs:20,settings:{}});
    if(p.startsWith('/api/'))return J({});return r.fulfill({status:404,body:''})});
  await pg.goto('http://x.test/');await pg.waitForTimeout(700);
  const o=await pg.evaluate(async()=>{document.body.classList.remove('cat');await loadPhotos();await new Promise(z=>setTimeout(z,250));
    const bar=document.querySelector('.bar'),main=document.querySelector('#main').getBoundingClientRect();
    const els=[...bar.querySelectorAll('button,select,input')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'});
    return {sw:bar.scrollWidth,cw:bar.clientWidth,mainTop:main.top,vw:innerWidth,vh:innerHeight,
      shown:['bUnrej','bSuggRate','bSuggClear'].map(i=>!document.getElementById(i).hidden),
      els:els.map(e=>{const r=e.getBoundingClientRect();return {id:e.id||e.tagName,l:r.left,r:r.right,t:r.top,b:r.bottom}})}});
  const tag=`${w}px ${busy?'có đề xuất':'chưa đề xuất'}`;
  assert.deepEqual(o.shown,[busy,busy,busy],tag+': nút hiện/ẩn sai');
  assert.ok(o.sw<=o.cw+1,`${tag}: thanh tràn ngang ${o.sw}/${o.cw}`);
  for(const e of o.els){
    assert.ok(e.l>=0&&e.r<=o.vw&&e.t>=0&&e.b<=o.vh,`${tag}: ${e.id} ra ngoài màn hình (${Math.round(e.l)}–${Math.round(e.r)})`);
    assert.ok(e.b<=o.mainTop,`${tag}: ${e.id} bị lưới đè (đáy ${e.b} > ${o.mainTop})`);
  }
  if(shots&&busy&&(w===1366||w===1920))await pg.screenshot({path:path.join(shots,`toolbar-${w}.png`)});
  await pg.close();
}
assert.deepEqual(errs,[]);
console.log('ok (toolbar fit)');await b.close()})().catch(e=>{console.error(e.message);process.exit(1)});
