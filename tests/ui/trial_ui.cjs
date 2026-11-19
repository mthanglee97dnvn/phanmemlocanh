// Dùng thử 3 ngày: màn hình kích hoạt tự xin key thử, nút Thử lại, nhãn "Dùng thử · còn N ngày" (node tests/ui/trial_ui.cjs)
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert');
const W=f=>fs.readFileSync(path.join(__dirname,'../../app/photosift/web',f));
const OFF='Cần kết nối mạng để bắt đầu dùng thử 3 ngày', EXP='Đã hết 3 ngày dùng thử — mua bản quyền vĩnh viễn 500.000đ để dùng tiếp';
async function run(b,{lic,trial},page='activate.html'){
  const pg=await b.newPage(),calls=[],errs=[];pg.on('pageerror',e=>errs.push(e.message));let L=lic;
  await pg.route('**/*',async r=>{const p=new URL(r.request().url()).pathname,J=o=>r.fulfill({body:JSON.stringify(o),contentType:'application/json'});calls.push(p);
    if(p==='/act')return r.fulfill({body:W(page),contentType:'text/html'});
    if(p==='/')return r.fulfill({body:'<html><body id="home">home</body></html>',contentType:'text/html'});
    if(p==='/api/license')return J(L);
    if(p==='/api/license/trial'){const t=trial.shift();if(t.ok)L={ok:true,trial:true,days_left:2};return J(t)}
    if(p.startsWith('/api/'))return J({});
    return r.fulfill({status:404,body:''})});
  await pg.goto('http://x.test/act');await pg.waitForTimeout(700);return {pg,calls,errs};}
(async()=>{const b=await chromium.launch();
// (a) chưa có key → tự xin thử → vào app
let {pg,calls,errs}=await run(b,{lic:{ok:false,has_key:false,machine:'AAAA-BBBB-CCCCC',has_pub:true},trial:[{ok:true}]});
assert.equal(calls.filter(c=>c==='/api/license/trial').length,1);assert.ok(await pg.$('#home'),'chuyển vào app');assert.deepEqual(errs,[]);await pg.close();
// (b) mất mạng → câu báo + Thử lại
({pg,calls,errs}=await run(b,{lic:{ok:false,has_key:false,machine:'AAAA-BBBB-CCCCC',has_pub:true},trial:[{ok:false,reason:OFF,offline:true},{ok:true}]}));
assert.equal((await pg.textContent('#err')).trim(),OFF);assert.ok(await pg.isVisible('#trialRetry'));
assert.match(await pg.textContent('#trialRetry'),/Thử lại/);
await pg.click('#trialRetry');await pg.waitForTimeout(500);
assert.equal(calls.filter(c=>c==='/api/license/trial').length,2);assert.ok(await pg.$('#home'));assert.deepEqual(errs,[]);await pg.close();
// (c) đã có key (thử hết hạn) → không xin lại, hiện câu hết hạn
({pg,calls,errs}=await run(b,{lic:{ok:false,has_key:true,expired:true,trial:true,reason:EXP,machine:'AAAA-BBBB-CCCCC',has_pub:true},trial:[]}));
assert.equal(calls.filter(c=>c==='/api/license/trial').length,0);assert.equal((await pg.textContent('#err')).trim(),EXP);
assert.ok(!(await pg.isVisible('#trialRetry')));assert.deepEqual(errs,[]);await pg.close();
// (d) shell: nhãn dùng thử
const sh=await b.newPage();const se=[];sh.on('pageerror',e=>se.push(e.message));
await sh.route('**/*',async r=>{const p=new URL(r.request().url()).pathname,J=o=>r.fulfill({body:JSON.stringify(o),contentType:'application/json'});
  if(p==='/')return r.fulfill({body:W('shell.html'),contentType:'text/html'});
  if(p==='/api/license')return J({ok:true,trial:true,permanent:false,days_left:2,machine:'AAAA-BBBB-CCCCC'});
  if(p==='/filter'||p==='/layout')return r.fulfill({body:'<html></html>',contentType:'text/html'});
  if(p.startsWith('/api/'))return J({});return r.fulfill({status:404,body:''})});
await sh.goto('http://x.test/');await sh.waitForTimeout(1200);
assert.equal((await sh.textContent('#tLic .t')).trim(),'Dùng thử · còn 3 ngày'  /* ngày đầu: tính cả hôm nay (M8) */);
await b.close();console.log('ok');
})().catch(e=>{console.error(e);process.exit(1);});
