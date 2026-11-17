// Trang điện thoại — iPad / màn rộng (node tests/ui/mobile_ipad.cjs)
const assert=require('assert'),{open,photo}=require('./mlib.cjs');
(async()=>{
  const ph=[]; for(let i=1;i<=60;i++) ph.push(photo(i));
  let T=await open({photos:ph,viewport:{width:1180,height:820}}); const pg=T.pg;
  assert.ok(await pg.evaluate(()=>M.split),'chia đôi');
  assert.ok(await pg.isVisible('#grid')&&await pg.isVisible('#view'),'lưới và Xem cùng hiện');
  assert.equal(await pg.evaluate(()=>G.n),5,'5 cột');
  const gw=await pg.$eval('#gridcol',e=>e.getBoundingClientRect().width); assert.ok(gw>1180*0.38&&gw<1180*0.5,'lưới ~44%: '+gw);
  await pg.click('.tile[data-id="7"]'); await pg.waitForTimeout(150);
  assert.equal(await pg.evaluate(()=>M.cur),7); assert.ok(await pg.isVisible('#grid'),'lưới vẫn hiện');
  assert.ok(await pg.$('.tile.cur[data-id="7"]'),'ô đang xem được đánh dấu');
  assert.ok(await pg.isVisible('#wCull')&&await pg.isVisible('#wSugg'),'nút Tự động lọc / Chọn ảnh đẹp trên thanh trên');
  assert.ok(!(await pg.isVisible('#vBack')),'không có nút về lưới');
  await pg.screenshot({path:process.env.SHOT||'/tmp/m-ipad.png'});
  // rotate keeps current: đang Xem id 12 ở dọc → ngang → iPad
  await pg.setViewportSize({width:390,height:844}); await pg.waitForTimeout(150);
  assert.ok(!(await pg.evaluate(()=>M.split)));
  await pg.evaluate(()=>openView(12)); await pg.waitForTimeout(100);
  await pg.setViewportSize({width:844,height:390}); await pg.waitForTimeout(150); assert.equal(await pg.evaluate(()=>M.cur),12);
  assert.ok(await pg.isVisible('#view'),'vẫn đang Xem');
  await pg.setViewportSize({width:1180,height:820}); await pg.waitForTimeout(150); assert.equal(await pg.evaluate(()=>M.cur),12);
  assert.ok(await pg.isVisible('#grid')&&await pg.isVisible('#view'));
  assert.deepEqual(T.errs,[]); await T.close();
  console.log('ok (mobile ipad)');
})().catch(e=>{console.error(e.message);process.exit(1)});
