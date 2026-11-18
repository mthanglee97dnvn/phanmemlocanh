// Thanh trạng thái .xmp: cảnh báo khi ghi lỗi, công tắc, nút Ghi lại; lưới tải lại khi đọc được .xmp mới (node tests/ui/xmp_ui.cjs)
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert');
const html=fs.readFileSync(path.join(__dirname,'../../app/photosift/web/index.html'),'utf8');
const ERR='Không ghi được .xmp vào thư mục này — kiểm tra quyền ghi trên NAS';
const mk=id=>({id,name:`MT_${id}.JPG`,dir:'/s',cam:'X',taken:id,w:64,h:48,rating:0,label:null,grp:0,best:0,score:50,sharp:1,fsharp:1,nf:0,people:[],flags:[],an:true,err:false,smile:-1,tv:1,sugg:0});
const PH=Array.from({length:6},(_,i)=>mk(i+1));
let ST={state:'done',root:'/s',online:true,eyes:true,total:6,done:6,thumbs:6,xmp_err:ERR,settings:{blur_ratio:.45,dark:.2,bright:.8,ear:.19,dup_hamming:10,dup_seconds:20,emotion_priority:1,face_threshold:.4,xmp_sync:1}};
const calls=[];
(async()=>{const b=await chromium.launch();const pg=await b.newPage({viewport:{width:1600,height:900}});
const errs=[];pg.on('pageerror',e=>errs.push(e.message));
await pg.route('**/*',async r=>{const u=new URL(r.request().url()),p=u.pathname,J=o=>r.fulfill({body:JSON.stringify(o),contentType:'application/json'});
  const bd=r.request().method()==='POST'?JSON.parse(r.request().postData()||'null'):undefined; calls.push([p,bd]);
  if(p==='/')return r.fulfill({body:html,contentType:'text/html'});
  if(p==='/cull.js')return r.fulfill({body:fs.readFileSync(path.join(__dirname,'../../app/photosift/web/cull.js')),contentType:'application/javascript'});
  if(p==='/api/photos')return J(PH);
  if(p==='/api/status')return J(ST);
  if(p==='/api/settings'){Object.assign(ST.settings,bd);return J({settings:ST.settings})}
  if(p==='/api/xmp/all'){ST={...ST};delete ST.xmp_err;return J({n:4,written:4,failed:0})}
  if(p.startsWith('/api/'))return J({});
  return r.fulfill({status:404,body:''})});
await pg.goto('http://x.test/');await pg.waitForTimeout(1200);
await pg.evaluate(()=>document.body.classList.remove('cat'));await pg.waitForTimeout(1000);
const W=ms=>pg.waitForTimeout(ms||150), n=k=>calls.filter(c=>c[0]===k);
// 1) cảnh báo lỗi ghi
assert.ok(await pg.isVisible('#sXmp'),'#sXmp hiện');
assert.equal((await pg.textContent('#sXmp')).trim(),ERR);
assert.ok(await pg.$eval('#sXmp',e=>e.classList.contains('warn')),'class warn');
// 2) hộp: nút Ghi lại
await pg.click('#sXmp');await W();
assert.ok(await pg.isVisible('#xmpAll'));assert.match(await pg.textContent('#xmpAll'),/Ghi lại \.xmp cho cả thư mục/);
await pg.click('#xmpAll');await W(400);
assert.equal(n('/api/xmp/all').length,1,'gọi /api/xmp/all');
// 3) công tắc
assert.ok(await pg.isChecked('#xmpSync'));
await pg.uncheck('#xmpSync');await W(300);
assert.deepEqual(n('/api/settings').slice(-1)[0][1],{xmp_sync:0});
await pg.keyboard.press('Escape');await W(1200);
assert.match((await pg.textContent('#sXmp')).trim(),/^\.xmp tắt$/);
// 4) xver đổi → tải lại danh sách ảnh
const before=n('/api/photos').length; ST={...ST,xver:1};await W(1500);
assert.ok(n('/api/photos').length>before,'tải lại ảnh khi xver đổi');
assert.deepEqual(errs,[]);await b.close();console.log('ok');
})().catch(e=>{console.error(e);process.exit(1);});
