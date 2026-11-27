// Ảnh Sony nhúng JPEG 1616px: xem vừa khung trên màn lớn phải chuyển sang bản nét (giải mã RAW), không để ảnh 1616 bị phóng nhòe.
// Lỗi cũ: needHQ() giả định ảnh cache của RAW dài 2048px → tưởng đủ nét, không bao giờ xin bản nét.
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert'),{execFileSync}=require('child_process'),os=require('os');
const html=fs.readFileSync(path.join(__dirname,'../../app/photosift/web/index.html'),'utf8');
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'vs-'));
execFileSync('python3',['-c',`import cv2,numpy as np,sys
for n,w,h in (('emb',1616,1080),('big',2048,1365),('hq',2304,1536)): cv2.imwrite(sys.argv[1]+'/'+n+'.jpg', np.full((h,w,3),128,np.uint8))`,tmp]);
const J=n=>fs.readFileSync(path.join(tmp,n+'.jpg'));
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
const mk=(id,name)=>({id,name,dir:'/s',cam:'X',taken:id,w:6000,h:4000,rating:0,label:null,grp:0,best:0,score:50,sharp:1,fsharp:1,nf:0,people:[],flags:[],an:true,err:false,smile:-1,tv:1,sugg:0});
async function run(emb){
  const b=await chromium.launch();const pg=await b.newPage({viewport:{width:2200,height:1310},deviceScaleFactor:1});
  const errs=[],hq=[];pg.on('pageerror',e=>errs.push(e.message));
  await pg.route('**/*',async r=>{const u=new URL(r.request().url()),p=u.pathname,Jo=o=>r.fulfill({body:JSON.stringify(o),contentType:'application/json'});
    if(p.split('?')[0].endsWith('/cull.js'))return r.fulfill({body:fs.readFileSync(path.join(__dirname,'../../app/photosift/web/cull.js')),contentType:'application/javascript'});
    if(p==='/')return r.fulfill({body:html,contentType:'text/html'});
    if(p==='/api/preview'){if(u.searchParams.get('hq')==='1'){hq.push(u.searchParams.get('id'));return r.fulfill({body:J('hq'),contentType:'image/jpeg'})}
      return r.fulfill({body:J(emb),contentType:'image/jpeg'})}
    if(p.startsWith('/thumb/'))return r.fulfill({body:png,contentType:'image/png'});
    if(p==='/api/photos')return Jo([mk(1,'TAN08067.ARW'),mk(2,'TAN08068.ARW')]);
    if(p==='/api/status')return Jo({state:'done',root:'/s',online:true,total:2,done:2,thumbs:2,settings:{}});
    if(p.startsWith('/api/'))return Jo({});
    return r.fulfill({status:404,body:''})});
  await pg.goto('http://x.test/');await pg.waitForTimeout(800);
  await pg.evaluate(async()=>{document.body.classList.remove('cat');await loadPhotos();S.cur=1;openViewer()});
  await pg.waitForTimeout(1500);
  const nw=await pg.$eval('#vimg',i=>i.naturalWidth);
  await b.close();
  assert.deepEqual(errs,[]);
  return {hq,nw};
}
(async()=>{
  const sony=await run('emb');
  assert.ok(sony.hq.includes('1'),'ảnh nhúng 1616px trên màn 2200px phải xin bản nét');
  assert.equal(sony.nw,2304,'khung xem phải đổi sang bản nét');
  const canon=await run('big');   // ảnh nhúng 2048px đã đủ nét cho khung ~1900px: không giải mã RAW (giữ đúng màu máy)
  assert.ok(!canon.hq.includes('1'),'ảnh nhúng đủ lớn thì không xin bản nét: '+canon.hq);
  assert.equal(canon.nw,2048);
  console.log('view_sharp ok');
})().catch(e=>{console.error(e);process.exit(1)});
