// Trang điện thoại — Lưới (node tests/ui/mobile_grid.cjs)
const assert=require('assert'),{open,photo}=require('./mlib.cjs');
(async()=>{
  // 30 ảnh, loạt grp=5 gồm id 1..5 (best id 3)
  const ph=[]; for(let i=1;i<=30;i++) ph.push(photo(i,i<=5?{grp:5,best:i===3?1:0,flags:i===3?[]:['dup']}:{}));
  ph[9].sugg=1; ph[10].flags=['blur']; ph[11].rating=2; ph[12].rating=-1; ph[13].people=[1]; ph[14].hl=true;
  const people=[{id:1,name:'Trâm Anh',n:300},{id:2,name:null,n:250},{id:3,name:'Khánh',n:120},{id:4,name:null,n:19}]
    .concat(Array.from({length:8},(_,k)=>({id:10+k,name:null,n:90-k})));
  people.push({id:99,name:'Chú Ân',n:60});
  let T=await open({photos:ph,people});
  const tiles=()=>T.pg.$$eval('.tile',e=>e.map(x=>({id:+x.dataset.id,n:x.querySelector('.cnt')?.textContent||''})));
  let t=await tiles();
  assert.equal(t.length,26,'gộp loạt: 26 ô, có '+t.length);
  assert.equal(t.find(x=>x.id===3).n,'×5');
  assert.ok(await T.pg.$('.tile[data-id="10"] .sg'),'✦'); assert.ok(await T.pg.$('.tile[data-id="11"] .wn'),'chip cảnh báo');
  assert.ok(await T.pg.$('.tile[data-id="12"] .st'),'sao'); assert.ok(await T.pg.$('.tile[data-id="13"].rej'),'đã loại');
  // lọc Đã loại khi 2 ảnh của loạt bị loại
  T.st.photos[0].rating=-1; T.st.photos[1].rating=-1; T.st.ver++;
  await T.pg.evaluate(()=>mSync(true)); await T.pg.waitForTimeout(150);
  await T.pg.click('.chip[data-f="rej"]'); t=await tiles();
  assert.deepEqual(t.map(x=>x.id).sort((a,b)=>a-b),[1,13]); assert.equal(t.find(x=>x.id===1).n,'×2');
  // loạt chỉ còn 1 ảnh trong lọc → không hiện ×1
  await T.pg.click('.chip[data-f="all"]'); T.st.photos.forEach(p=>{if(p.grp)p.rating=0}); T.st.photos[0].rating=-1; T.st.ver++; await T.pg.evaluate(()=>mSync(true)); await T.pg.waitForTimeout(100);
  await T.pg.click('.chip[data-f="rej"]'); t=await tiles(); assert.equal(t.find(x=>x.id===1).n,'');
  await T.pg.click('.chip[data-f="all"]');
  // chip người: có tên trước, ≤10, có Highlight
  const chips=await T.pg.$$eval('.chip[data-f^="p:"]',e=>e.map(x=>x.textContent.trim()));
  assert.ok(chips.length<=10,'≤10 chip người'); assert.ok(/Trâm Anh/.test(chips[0])&&/Khánh/.test(chips[1])&&/Chú Ân/.test(chips[2]),'tên trước: '+chips.slice(0,3));
  assert.ok(!chips.some(c=>/Người 4\b/.test(c)),'người <20 ảnh không có chip');
  assert.ok(await T.pg.$('.chip[data-f="hl"]'),'chip Highlight');
  // 4 cột, nhớ sau khi tải lại
  await T.pg.evaluate(()=>mSetCols(4)); assert.equal(await T.pg.evaluate(()=>getComputedStyle(document.querySelector('.row')).gridTemplateColumns.split(' ').length),4);
  await T.pg.reload(); await T.pg.waitForTimeout(500); assert.equal(await T.pg.evaluate(()=>M.cols),4);
  assert.deepEqual(T.errs,[]); await T.close();
  // cuộn ảo hoá 3000 ảnh
  const big=[]; for(let i=1;i<=3000;i++) big.push(photo(i));
  T=await open({photos:big}); assert.ok((await T.pg.$$('.tile')).length<400,'DOM ít ô');
  await T.pg.evaluate(()=>{const g=document.getElementById('grid'); g.scrollTop=g.scrollHeight/2; g.dispatchEvent(new Event('scroll'));}); await T.pg.waitForTimeout(150);
  const ids=await T.pg.$$eval('.tile',e=>e.map(x=>+x.dataset.id)); assert.ok(ids.some(i=>i>1300&&i<1700),'đã vẽ đoạn giữa'); assert.ok(ids.length<400);
  // đồng bộ: ver đổi → tải lại /api/photos đúng 1 lần, giữ vị trí cuộn
  const top=await T.pg.evaluate(()=>document.getElementById('grid').scrollTop);
  const before=T.st.calls.filter(c=>c.path==='/api/photos').length; T.st.ver++; T.st.photos[1500].rating=3;
  await T.pg.evaluate(()=>mSync()); await T.pg.waitForTimeout(150); await T.pg.evaluate(()=>mSync()); await T.pg.waitForTimeout(150);
  assert.equal(T.st.calls.filter(c=>c.path==='/api/photos').length-before,1,'tải lại đúng 1 lần');
  assert.equal(await T.pg.evaluate(()=>document.getElementById('grid').scrollTop),top);
  await T.pg.screenshot({path:process.env.SHOT||'/tmp/m-grid.png'}); assert.deepEqual(T.errs,[]); await T.close();
  // test_empty_states
  T=await open({photos:[]}); assert.ok(/Chưa có ảnh/.test(await T.pg.textContent('body'))); assert.deepEqual(T.errs,[]); await T.close();
  console.log('ok (mobile grid)');
})().catch(e=>{console.error(e.message);process.exit(1)});
