/* Dùng chung máy tính + điện thoại: ảnh nào "Tự động lọc" sẽ đánh dấu loại.
   photos: [{rating, flags}], sel ⊆ ['blur','dark','bright','eyes','dup'] → ảnh chưa chấm dính ít nhất một cảnh báo đã chọn. */
function cullCandidates(photos, sel){
  return (photos||[]).filter(function(p){ return p.rating===0 && (p.flags||[]).some(function(f){ return sel.indexOf(f)>=0; }); });
}
if(typeof window!=='undefined') window.cullCandidates=cullCandidates;
