// Ô đếm cặp RAW–JPEG trên thanh công cụ (node tests/ui/pair_ui.cjs)
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert');
const html=fs.readFileSync(path.join(__dirname,'../../app/photosift/web/index.html'),'utf8');
(async()=>{const b=await chromium.launch();const pg=await b.newPage({viewport:{width:1500,height:800}});
const errs=[];pg.on('pageerror',e=>errs.push(e.message));
await pg.route('**/*',r=>{if(r.request().url().split('?')[0].endsWith('/cull.js'))return r.fulfill({body:require('fs').readFileSync(require('path').join(__dirname,'../../app/photosift/web/cull.js')),contentType:'application/javascript'});const u=r.request().url();
  if(u.endsWith('/'))return r.fulfill({body:html,contentType:'text/html'});
  if(u.includes('/api/'))return r.fulfill({body:'{}',contentType:'application/json'});
  return r.fulfill({body:'',status:404})});
await pg.goto('http://x.test/');await pg.waitForTimeout(900);
const mk=(id,name,t)=>({id,name,dir:'/s',cam:'X',taken:t,w:64,h:48,rating:0,label:null,grp:0,best:0,score:50,sharp:1,fsharp:1,nf:0,people:[],flags:[],an:true,err:false,smile:-1});
await pg.evaluate(ph=>{document.body.classList.remove('cat');S.photos=ph;applyView();window.__t=[];const o=toast;window.toast=(m,ms)=>{__t.push(m);o(m,ms)}},
  [mk(1,'A.ARW',1),mk(2,'A.JPG',1),mk(3,'B.ARW',2)]);
await pg.click('#pairCnt');
assert.equal(await pg.evaluate(()=>S.filter),'odd');
assert.ok(await pg.isDisabled('#fSort'),'đang lọc file lẻ: ô Sắp xếp phải mờ đi');
assert.match(await pg.getAttribute('#fSort','title'),/file lẻ/);
// mở sang thư mục chỉ có JPEG khi đang lọc file lẻ → về Tất cả, KHÔNG báo "đủ cặp"
await pg.evaluate(()=>{S.photos=[1,2].map(i=>({...S.photos[0],id:10+i,name:'J'+i+'.JPG'}));applyView()});
assert.equal(await pg.evaluate(()=>S.filter),'all');
assert.deepEqual(await pg.evaluate(()=>__t.filter(m=>/đủ cặp/.test(m))),[],'thư mục chỉ JPEG không được báo "đủ cặp"');
assert.ok(!(await pg.isDisabled('#fSort')),'rời bộ lọc file lẻ: ô Sắp xếp dùng lại được');
assert.deepEqual(errs,[]);
console.log('ok (pair ui)');await b.close()})().catch(e=>{console.error(e.message);process.exit(1)});
