export const CUSTOMER_SEARCH_BRIDGE_SNIPPET=`<script>(()=>{
const input=document.getElementById('customerSearch');if(!input)return;
const cyrMap={
 'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'j','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'x','ц':'ts','ч':'ch','ш':'sh','щ':'sh','ъ':'','ы':'i','ь':'','э':'e','ю':'yu','я':'ya','қ':'q','ғ':'g','ҳ':'h','ў':'o'
};
function norm(v){
 let s=String(v||'').toLowerCase();
 s=s.replace(/[а-яёқғҳў]/g,ch=>cyrMap[ch]??ch);
 return s.replace(/o[‘’'ʻʼ`]/g,'o').replace(/g[‘’'ʻʼ`]/g,'g').replace(/[\\s()+\\-_.‘’'ʻʼ`]/g,'');
}
function run(){
 const q=norm(input.value),rows=[...document.querySelectorAll('[data-customer-row]')],cards=[...document.querySelectorAll('[data-customer-card]')];let rd=0,rm=0;
 rows.forEach(el=>{const ok=!q||norm(el.dataset.customerSearch).includes(q);el.style.display=ok?'':'none';if(ok)rd++});
 cards.forEach(el=>{const ok=!q||norm(el.dataset.customerSearch).includes(q);el.style.display=ok?'':'none';if(ok)rm++});
 const de=document.getElementById('customerEmptyDesktop'),me=document.getElementById('customerEmptyMobile');
 if(de)de.style.display=q&&rd===0?'table-row':'none';
 if(me)me.style.display=q&&rm===0?'block':'none';
}
input.addEventListener('input',run);input.addEventListener('search',run);setTimeout(run,0);
})();</script>`;
