// "Chọn ảnh đẹp" trong Tự động lọc, bộ lọc ✦ Đề xuất, hộp "Gu chọn ảnh" — index.html với API giả
// node tests/ui/taste_ui.cjs [thư_mục_ảnh_chụp]   (có thư mục → lưu taste-dialog.png, taste-gu.png, taste-grid.png)
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert');
const html=fs.readFileSync(path.join(__dirname,'../../app/photosift/web/index.html'),'utf8');
const shots=process.argv[2]||'';
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
const mk=id=>({id,name:`MT_${String(id).padStart(4,'0')}.JPG`,dir:'/s',cam:'X',taken:id,w:64,h:48,rating:0,label:null,grp:0,best:0,score:50,sharp:1,fsharp:1,nf:0,people:[],flags:id===4?['blur']:[],an:true,err:false,smile:-1,tv:1,sugg:0});
const PH=Array.from({length:20},(_,i)=>mk(i+1));
const ROLLS=[{root:'/w/2026-10-01 Hoa & Nam',n:812,kept:304,on:true},{root:'C:\\Wedding\\Tuấn - Linh',n:540,kept:121,on:true},{root:'/w/<i>x',n:90,kept:20,on:true}];
let TASTE={source:'default',rolls:ROLLS,n_rolls:3,n_photos:1442,agree:null,learned:null,stale:false};
let SUGG={ids:[1,2,3],note:'Bạn đã chọn 5 tấm, nhiều hơn 400'};
const calls=[];
(async()=>{const b=await chromium.launch();const pg=await b.newPage({viewport:{width:1920,height:1000},deviceScaleFactor:1});
const errs=[];pg.on('pageerror',e=>errs.push(e.message));
await pg.route('**/*',async r=>{const u=new URL(r.request().url()), J=o=>r.fulfill({body:JSON.stringify(o),contentType:'application/json'});
  const bd=r.request().method()==='POST'?JSON.parse(r.request().postData()||'null'):undefined, p=u.pathname;
  if(p==='/')return r.fulfill({body:html,contentType:'text/html'});
  if(p.startsWith('/thumb/')||p==='/api/preview')return r.fulfill({body:png,contentType:'image/png'});
  if(p.startsWith('/api/taste')||p.startsWith('/api/suggest'))calls.push([p,bd]);
  if(p==='/api/photos')return J(PH);
  if(p==='/api/status')return J({state:'done',root:'/s',online:true,eyes:true,total:20,done:20,thumbs:20,settings:{blur_ratio:.45,dark:.2,bright:.8,ear:.19,dup_hamming:10,dup_seconds:20,emotion_priority:1,face_threshold:.4}});
  if(p==='/api/taste')return J(TASTE);
  if(p==='/api/taste/learn'){await new Promise(z=>setTimeout(z,400));TASTE={...TASTE,stale:false};return J(TASTE)}
  if(p==='/api/taste/rolls'){const off=new Set(bd.off);TASTE={...TASTE,rolls:ROLLS.map(x=>({...x,on:!off.has(x.root)})),stale:true};return J(TASTE)}
  if(p==='/api/taste/export')return J({ok:true,path:bd.dest+'/taste_data.npz',rows:1442});
  if(p==='/api/suggest'){PH.forEach(x=>x.sugg=SUGG.ids.includes(x.id)?1:0);return J({ids:SUGG.ids,n:SUGG.ids.length,note:SUGG.note,source:TASTE.source})}
  if(p==='/api/suggest/clear'){PH.forEach(x=>x.sugg=0);return J({ok:true})}
  if(p==='/api/suggest/rate'){PH.forEach(x=>{if(x.sugg&&!x.rating)x.rating=1});return J({ok:true,n:2,batch:7,ids:[1,2]})}
  if(p==='/api/suggest/rate/undo'){PH.forEach(x=>{if(x.id<=2)x.rating=0});return J({ok:true,n:2,ids:[1,2]})}
  if(p.startsWith('/api/'))return J({});
  return r.fulfill({status:404,body:''})});
await pg.goto('http://x.test/');await pg.waitForTimeout(900);
await pg.evaluate(async()=>{document.body.classList.remove('cat');try{localStorage.removeItem('ps.suggN')}catch(e){}
  window.__t=[];const o=toast;window.toast=(m,ms)=>{__t.push(m);o(m,ms)};await loadPhotos()});
const W=ms=>pg.waitForTimeout(ms||120), n=k=>calls.filter(c=>c[0]===k), toasts=()=>pg.evaluate(()=>__t.slice());
const shown=async s=>!!(await pg.$(s))&&await pg.isVisible(s);

// 1) mở Tự động lọc → phần "Chọn ảnh đẹp" + dòng gu đang dùng
await pg.click('#bCull');await W(250);
assert.ok(await pg.$('#k_blur'),'phần Loại ảnh lỗi vẫn còn');
assert.match(await pg.textContent('#tSec'),/Chọn ảnh đẹp/);
assert.match(await pg.textContent('#tInfo'),/Đang dùng: gu mặc định/);
assert.equal(await pg.inputValue('#tN'),'12%','mặc định 12%');
assert.equal(n('/api/taste/learn').length,0,'stale=false: không tự học');
if(shots)await pg.screenshot({path:path.join(shots,'taste-dialog.png')});
await pg.fill('#tN','400');await pg.click('#tGo');await W(300);
assert.deepEqual(n('/api/suggest').at(-1)[1],{n:400});
assert.ok(!(await pg.$('.back')),'đề xuất xong thì đóng hộp');
// 2) sau đề xuất: bộ lọc sugg, dấu ✦, hai nút thanh
assert.equal(await pg.evaluate(()=>S.filter),'sugg');
assert.equal(await pg.inputValue('#fFilter'),'sugg');
assert.match(await pg.$eval('#fFilter option[value=sugg]',o=>o.textContent),/^✦ Đề xuất/);
assert.equal(await pg.$$eval('#grid .cell',c=>c.length),3);
assert.equal(await pg.$$eval('#grid .cell .sugg',c=>c.length),3,'ô đề xuất có dấu ✦');
assert.ok(await shown('#bSuggRate')&&await shown('#bSuggClear'),'hai nút thanh hiện khi có đề xuất');
assert.match(await pg.textContent('#bSuggRate'),/Chấm 1 sao cho tất cả đề xuất/);
let t=await toasts();assert.ok(t.some(m=>/Đã đề xuất 3 tấm/.test(m)&&/nhiều hơn 400/.test(m)),'toast có note "nhiều hơn": '+t);
// lưới Tất cả: chỉ ô đề xuất có ✦
await pg.selectOption('#fFilter','all');await W();
assert.equal(await pg.$$eval('#grid .cell .sugg',c=>c.length),3);
assert.equal(await pg.$$eval('#grid .cell',c=>c.length),20);
if(shots)await pg.screenshot({path:path.join(shots,'taste-grid.png')});
// 3) nhớ N lần trước; gõ 15% → 15% của 20 ảnh = 3
SUGG={ids:[5,6],note:'chỉ tìm được 2 tấm khác nhau'};
await pg.click('#bCull');await W(250);
assert.equal(await pg.inputValue('#tN'),'400','nhớ số lần trước');
await pg.fill('#tN','15%');await pg.press('#tN','Enter');await W(300);
assert.deepEqual(n('/api/suggest').at(-1)[1],{n:3});
t=await toasts();assert.ok(t.some(m=>/Đã đề xuất 2 tấm/.test(m)&&/chỉ tìm được/.test(m)),'toast có note "chỉ tìm được": '+t);
assert.equal(await pg.evaluate(()=>localStorage.getItem('ps.suggN')),'15%');
// gõ bậy → không gọi máy chủ
await pg.click('#bCull');await W(250);const k0=n('/api/suggest').length;
await pg.fill('#tN','abc');await pg.click('#tGo');await W();
assert.equal(n('/api/suggest').length,k0,'số không hợp lệ: không gọi đề xuất');assert.ok(await pg.$('.back'));
await pg.keyboard.press('Escape');await W();
// 4) Chấm 1 sao cho tất cả đề xuất → hoàn tác được
PH.forEach(x=>x.sugg=[1,2,3].includes(x.id)?1:0);await pg.evaluate(()=>loadPhotos());await W();
await pg.click('#bSuggRate');await W(200);
assert.deepEqual(n('/api/suggest/rate').at(-1)[1],{});
t=await toasts();assert.ok(t.some(m=>/Đã chấm 1 sao cho 2 ảnh/.test(m)),'toast có số ảnh: '+t);
assert.deepEqual(await pg.evaluate(()=>S.undo.at(-1)),{t:'suggrate',batch:7});
assert.deepEqual(await pg.evaluate(()=>[1,2,3].map(i=>S.by.get(i).rating)),[1,1,0]);
assert.ok(!(await pg.isDisabled('#bUndo')));
await pg.click('#bUndo');await W(200);
assert.deepEqual(n('/api/suggest/rate/undo').at(-1)[1],{batch:7});
assert.deepEqual(await pg.evaluate(()=>[1,2].map(i=>S.by.get(i).rating)),[0,0]);
assert.ok(!(await pg.evaluate(()=>S.undo.some(u=>u.t==='suggrate'))));
// 5) hộp Gu chọn ảnh (mở từ phần Chọn ảnh đẹp)
await pg.click('#bCull');await W(250);await pg.click('#tTaste');await W(250);
assert.equal(await pg.$$eval('.back',x=>x.length),1,'hộp Gu thay hộp Tự động lọc');
assert.deepEqual(await pg.$$eval('.grow .gn',x=>x.map(e=>e.textContent)),['2026-10-01 Hoa & Nam','Tuấn - Linh','<i>x'],'tên đám = đoạn cuối đường dẫn, đã escape');
assert.equal(await pg.$$eval('.glist i',x=>x.length),0,'chuỗi máy chủ phải được escape');
assert.match(await pg.textContent('.back .modal'),/Mỗi đám cũ cần được mở trong app một lần để app đo ảnh\./);
assert.match(await pg.textContent('.back .modal'),/812 ảnh/);
assert.ok(!(await pg.$('#gExp')),'không giữ Alt: ẩn nút Xuất dữ liệu học');
if(shots)await pg.screenshot({path:path.join(shots,'taste-gu.png')});
await pg.click('.grow:nth-child(1) input');await W(200);
assert.deepEqual(n('/api/taste/rolls').at(-1)[1],{off:['/w/2026-10-01 Hoa & Nam']});
await pg.click('#gLearn');await W(60);
assert.ok(await pg.isDisabled('#gLearn'),'đang học: khóa nút');
await pg.$eval('#gLearn',e=>e.click());await W(60);
assert.equal(n('/api/taste/learn').length,1,'không gửi 2 lần');assert.deepEqual(n('/api/taste/learn')[0][1],{});
await W(500);assert.ok(!(await pg.isDisabled('#gLearn')),'học xong mở lại nút');
// Dùng lại gu mặc định = tắt mọi đám rồi học lại
const L0=n('/api/taste/learn').length;
await pg.click('#gReset');await W(700);
assert.deepEqual(n('/api/taste/rolls').at(-1)[1],{off:ROLLS.map(x=>x.root)});
assert.equal(n('/api/taste/learn').length,L0+1);
assert.equal(await pg.$$eval('.grow input:checked',x=>x.length),0);
await pg.keyboard.press('Escape');await W();
// Alt + mở hộp → nút Xuất dữ liệu học
await pg.click('#bCull');await W(250);await pg.click('#tTaste',{modifiers:['Alt']});await W(250);
assert.ok(await shown('#gExp'),'giữ Alt: hiện nút Xuất dữ liệu học');
assert.match(await pg.textContent('#gExp'),/Xuất dữ liệu học/);
await pg.click('#gExp');await pg.fill('#gDest','/tmp/gu');await pg.click('#gExpGo');await W(200);
assert.deepEqual(n('/api/taste/export').at(-1)[1],{dest:'/tmp/gu'});
t=await toasts();assert.ok(t.some(m=>m.includes('/tmp/gu/taste_data.npz')),'toast đường dẫn file: '+t);
await pg.keyboard.press('Escape');await W();
// 6) gu cũ (stale) + có đám bật → mở phần Chọn ảnh đẹp tự học nền
TASTE={...TASTE,rolls:ROLLS,source:'personal',n_rolls:12,agree:0.78,stale:true};
const L1=n('/api/taste/learn').length;
await pg.click('#bCull');await W(250);
assert.equal(n('/api/taste/learn').length,L1+1,'stale: tự học nền');
assert.ok(!(await pg.isDisabled('#tGo')),'học nền không khóa giao diện');
await W(600);
assert.match(await pg.textContent('#tInfo'),/Đang dùng: gu của bạn \(học từ 12 đám, trùng khớp 78%\)/);
await pg.keyboard.press('Escape');await W();
// 7) Bỏ đề xuất
await pg.selectOption('#fFilter','sugg');await W();
await pg.click('#bSuggClear');await W(250);
assert.deepEqual(n('/api/suggest/clear').at(-1)[1],{});
assert.equal(await pg.evaluate(()=>S.filter),'all');
assert.ok(!(await shown('#bSuggRate'))&&!(await shown('#bSuggClear')),'hết đề xuất: ẩn hai nút');
assert.equal(await pg.$$eval('#grid .cell .sugg',c=>c.length),0);
assert.deepEqual(errs,[]);
console.log('ok (taste ui)');await b.close()})().catch(e=>{console.error(e.message);process.exit(1)});
