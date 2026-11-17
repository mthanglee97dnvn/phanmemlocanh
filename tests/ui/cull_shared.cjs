// cullCandidates dùng chung máy tính + điện thoại (node tests/ui/cull_shared.cjs)
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const ctx={window:{}};ctx.window=ctx;vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../app/photosift/web/cull.js'),'utf8'),ctx);
const P=(id,rating,flags)=>({id,rating,flags});
const ph=[P(1,0,['blur']),P(2,1,['blur']),P(3,0,['dup']),P(4,0,[]),P(5,-1,['eyes']),P(6,0,['eyes','dark'])];
assert.deepEqual(ctx.cullCandidates(ph,['blur','eyes']).map(p=>p.id),[1,6]);
assert.deepEqual(ctx.cullCandidates(ph,['dup']).map(p=>p.id),[3]);
assert.deepEqual(ctx.cullCandidates(ph,[]).map(p=>p.id),[]);
console.log('ok (cull shared)');
