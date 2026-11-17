// Bộ dựng chung cho các bài thử trang điện thoại (mobile.html) với API giả.
const {chromium}=require('playwright'),fs=require('fs'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../../app/photosift/web/mobile.html'),'utf8');
const cull=fs.readFileSync(path.join(__dirname,'../../app/photosift/web/cull.js'));
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
function photo(id,o){return Object.assign({id,name:'IMG_'+String(id).padStart(4,'0')+'.ARW',dir:'/s',rating:0,label:null,grp:0,best:0,score:50,sharp:1,fsharp:1,nf:1,
  flags:[],people:[],hl:false,sugg:0,taken:1790000000+id*2,focus:null,w:6000,h:4000,tv:1,cam:'A',smile:-1,scene:null},o||{});}
async function open(opts){
  opts=opts||{};
  const st={photos:opts.photos||[],people:opts.people||[],ver:1,calls:[],rateFail:false,taste:opts.taste||{source:'basic',rolls:[],n_rolls:0,agree:null}};
  const b=await chromium.launch();
  const ctx=await b.newContext({viewport:opts.viewport||{width:390,height:844},hasTouch:true,isMobile:!opts.desktop,deviceScaleFactor:opts.dpr||1});
  const pg=await ctx.newPage(); const errs=[]; pg.on('pageerror',e=>errs.push(e.message));
  await ctx.route('**/*',async r=>{const u=new URL(r.request().url()),q=u.searchParams,m=r.request().method(),J=(o,s)=>r.fulfill({status:s||200,body:JSON.stringify(o),contentType:'application/json'});
    let body=null; try{body=JSON.parse(r.request().postData()||'null')}catch(e){}
    st.calls.push({path:u.pathname,q:Object.fromEntries(q),m,body});
    if(u.pathname==='/m')return r.fulfill({body:html,contentType:'text/html'});
    if(u.pathname==='/cull.js')return r.fulfill({body:cull,contentType:'application/javascript'});
    if(u.pathname.startsWith('/thumb/')||u.pathname==='/api/preview')return r.fulfill({body:png,contentType:'image/png'});
    if(u.pathname==='/api/photos')return J(st.photos);
    if(u.pathname==='/api/photos/ver')return J({ver:st.ver});
    if(u.pathname==='/api/people')return J(st.people);
    if(u.pathname==='/api/status')return J({state:'done',root:'/s/Anh-Khanh',online:true,settings:{}});
    if(u.pathname==='/api/catalog')return J([]);
    if(u.pathname==='/api/taste')return J(st.taste);
    if(u.pathname==='/api/rate'){ if(st.rateFail)return J({error:'x'},500); for(const id of body.ids){const p=st.photos.find(x=>x.id===id); if(p)p.rating=body.rating;} return J({ok:true}); }
    if(u.pathname==='/api/cull/apply'){ body.ids.forEach(id=>{const p=st.photos.find(x=>x.id===id); if(p)p.rating=-1}); return J({ok:true,batch:7,n:body.ids.length}); }
    if(u.pathname==='/api/cull/undo'){ return J({ok:true,n:1}); }
    if(u.pathname==='/api/suggest'){ const ids=st.photos.slice(0,body.n).map(p=>p.id); st.photos.forEach(p=>p.sugg=ids.includes(p.id)?1:0); return J({ids,n:ids.length,note:'',source:'basic'}); }
    if(u.pathname==='/api/suggest/clear'){ st.photos.forEach(p=>p.sugg=0); return J({ok:true}); }
    if(u.pathname==='/api/suggest/rate'){ const ids=st.photos.filter(p=>p.sugg&&p.rating===0).map(p=>p.id); ids.forEach(id=>st.photos.find(p=>p.id===id).rating=1); return J({ok:true,n:ids.length,batch:3,ids}); }
    if(u.pathname==='/api/suggest/rate/undo')return J({ok:true,n:1,ids:[]});
    if(u.pathname.startsWith('/api/'))return J({});
    if(u.hostname.includes('fonts'))return r.fulfill({body:'',contentType:'text/css'});
    return r.fulfill({status:404,body:''});});
  await pg.goto('http://x.test/m'); await pg.waitForTimeout(600);
  return {b,pg,st,errs,close:()=>b.close()};
}
module.exports={open,photo};
