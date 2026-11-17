// Màn hình "Ghép khoảnh khắc chung": chạy index.html với API giả (node tests/ui/moment_sync.cjs [ảnh_chụp.png])
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert');
const html=fs.readFileSync(path.join(__dirname,'../../app/photosift/web/index.html'),'utf8');
const T=1790000000, A='SONY · ILCE-7RM3 · 111', B='SONY · ILCE-7M4 · 222', C='Canon · R6 · 333';
// máy B chạy chậm 7 giây; có 3 tấm cùng giây (ids 21,22,23); thêm 1 tấm lệch cả ngày (id 30)
const PH={[A]:[[1,T+0],[2,T+31],[3,T+100],[4,T+200],[5,T+300]],
          [B]:[[20,T+10],[21,T+24],[22,T+24],[23,T+24],[24,T+193],[30,T+24-86400+86400*2]],
          [C]:[[40,T+5],[41,T+6]]};
const calls=[];
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
(async()=>{const b=await chromium.launch();const pg=await b.newPage({viewport:{width:1300,height:900},deviceScaleFactor:2});
const errs=[];pg.on('pageerror',e=>errs.push(e.message));
await pg.route('**/*',async r=>{const u=new URL(r.request().url()), q=u.searchParams, J=o=>r.fulfill({body:JSON.stringify(o),contentType:'application/json'});
  if(u.pathname==='/')return r.fulfill({body:html,contentType:'text/html'});
  if(u.pathname==='/api/preview')return r.fulfill({body:png,contentType:'image/png'});
  if(u.pathname==='/api/cameras/list')return J({cams:[{key:A,n:5,offset:0,first:1},{key:B,n:6,offset:0,first:20},{key:C,n:2,offset:0,first:40}]});   // máy chủ đã xếp theo số ảnh
  if(u.pathname==='/api/cameras/photos')return J({photos:PH[q.get('cam')]||[]});
  if(u.pathname==='/api/cameras/estimate'){calls.push(['estimate',q.get('ref'),q.get('cam')]);return J({offset:q.get('cam')===B?7:0,conf:0.8,source:'auto'})}
  if(u.pathname==='/api/cameras/pair'){const bd=JSON.parse(r.request().postData());calls.push(['pair',bd]);return J({ok:true,cam:B,offset:7,n:6})}
  if(u.pathname.startsWith('/api/'))return J({});
  return r.fulfill({status:404,body:''})});
await pg.goto('http://x.test/');await pg.waitForTimeout(900);
await pg.evaluate(()=>{document.body.classList.remove('cat');window.loadPhotos=async()=>{};});
await pg.evaluate(()=>openMomentSync(2));await pg.waitForTimeout(400);
const st=()=>pg.evaluate(()=>({L:document.querySelector('#mmLName').textContent,R:document.querySelector('#mmRName').textContent,res:document.querySelector('#mmRes').textContent,Lcam:document.querySelector('#mmLCam').value,Rcam:document.querySelector('#mmRCam').value,img:document.querySelector('#mmRImg').getAttribute('src')}));
let s=await st();
assert.ok(s.L.startsWith('2/5'),'trái bắt đầu ở tấm đang chọn: '+s.L);
assert.equal(s.Lcam,A); assert.equal(s.Rcam,B);
assert.ok(s.img.includes('id=21'),'phải tự nhảy tới tấm gần khoảnh khắc nhất: '+s.img);
assert.match(s.res,/^Lệch: \+7 giây \(máy chạy chậm\) · áp cho 6 ảnh của SONY · ILCE-7M4 · 222/);
await pg.screenshot({path:process.argv[2]||path.join(require('os').tmpdir(),'moment.png')});
// → đi từng tấm qua 3 tấm cùng giây
await pg.focus('#mmGo');
for(const id of [22,23]){await pg.keyboard.press('ArrowRight');await pg.waitForTimeout(60);assert.ok((await st()).img.includes('id='+id),'→ tới '+id)}
await pg.keyboard.press('ArrowLeft');await pg.keyboard.press('ArrowLeft');await pg.waitForTimeout(60);
assert.ok((await st()).img.includes('id=21'));
// Shift+→ đổi bên trái
await pg.keyboard.press('Shift+ArrowRight');await pg.waitForTimeout(60);s=await st();
assert.ok(s.L.startsWith('3/5'),'Shift+→ lật trái: '+s.L);
assert.match(s.res,/^Lệch: \+1 phút 16 giây/);
await pg.keyboard.press('Shift+ArrowLeft');await pg.waitForTimeout(60);
// thanh kéo về 0 → tấm B đầu tiên
await pg.$eval('#mmRange',e=>{e.value=0;e.dispatchEvent(new Event('input'))});await pg.waitForTimeout(60);
assert.ok((await st()).img.includes('id=20'));
// ô ± 1 ngày (trừ) → phải nhảy tới tấm lệch ngày (id 30: giờ = mốc + 1 ngày − 7 giây)
await pg.selectOption('#mmSg','-1');await pg.fill('#mmD','1');await pg.fill('#mmS','0');await pg.$eval('#mmD',e=>e.dispatchEvent(new Event('change')));await pg.waitForTimeout(60);
s=await st(); assert.ok(s.img.includes('id=30'),'± 1 ngày: '+s.img);
assert.match(s.res,/^Lệch: −23 giờ 59 phút 53 giây \(máy chạy nhanh\)/);
// về lại 21 rồi áp
await pg.fill('#mmD','0');await pg.selectOption('#mmSg','1');await pg.fill('#mmS','7');await pg.$eval('#mmS',e=>e.dispatchEvent(new Event('change')));await pg.waitForTimeout(60);
assert.ok((await st()).img.includes('id=21'));
await pg.click('#mmGo');await pg.waitForTimeout(150);
const pair=calls.filter(c=>c[0]==='pair');
assert.deepEqual(pair,[['pair',{ref:2,id:21}]]);
assert.ok((await pg.$eval('#mmRCam',e=>e.selectedOptions[0].textContent)).includes('đang lệch +7 giây'));
assert.ok(await pg.$('#mmGo'),'hộp vẫn mở sau khi áp');
// chọn máy C bên phải → hỏi ước lượng cho C
await pg.selectOption('#mmRCam',C);await pg.waitForTimeout(120);
assert.ok(calls.some(c=>c[0]==='estimate'&&c[2]===C));
// chọn bên phải trùng máy mốc → từ chối, giữ máy cũ
await pg.selectOption('#mmRCam',A);await pg.waitForTimeout(80);
assert.equal((await st()).Rcam,C);
assert.deepEqual(errs,[]);
console.log('ok (moment sync)');await b.close()})().catch(e=>{console.error(e.message);process.exit(1)});
