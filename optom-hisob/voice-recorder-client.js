export const VOICE_RECORDER_SNIPPET=`<style>
.voice-recorder{margin-top:6px;border:1px solid #d4ddd2;border-radius:12px;background:#f8faf7;padding:10px;color-scheme:light}.voice-recorder-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.voice-rec-btn{border:0;border-radius:10px;min-height:42px;padding:9px 13px;background:#126c43;color:#fff;font:800 13px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;cursor:pointer}.voice-rec-btn.recording{background:#b23c31}.voice-rec-time{font:800 12px/1 monospace;color:#526158;min-width:42px}.voice-rec-status{font-size:11px;color:#718078;font-weight:700}.voice-preview{display:none;width:100%;max-width:380px;height:40px;margin-top:9px}.voice-preview.show{display:block}.voice-rec-actions{display:none;gap:6px;margin-top:8px;flex-wrap:wrap}.voice-rec-actions.show{display:flex}.voice-mini{border:1px solid #d4ddd2;background:#fff;color:#304038;border-radius:9px;min-height:34px;padding:7px 10px;font:800 11px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;cursor:pointer}.voice-fallback{margin-top:8px}.voice-fallback input{display:block!important;width:100%!important}.voice-hidden-input{display:none!important}@media(max-width:760px){.voice-recorder{padding:9px}.voice-rec-btn{min-height:46px;font-size:14px}.voice-preview{max-width:100%;height:44px}}
</style><script>(()=>{
const LANG=()=>localStorage.getItem('optom_hisob_lang')||'uz_lat';
const TXT={
 uz_lat:{record:'🎙 Ovoz yozish',stop:'■ To‘xtatish',ready:'Ovoz yozishga tayyor',recording:'Ovoz yozilmoqda…',recorded:'Yozildi. ▶️ bosib eshitib ko‘ring.',again:'Qayta yozish',remove:'O‘chirish',denied:'Mikrofonga ruxsat berilmadi',unsupported:'Bu brauzerda ovoz yozish ishlamaydi. Audio fayl tanlang.',fallback:'Audio fayl tanlash'},
 uz_cyr:{record:'🎙 Овоз ёзиш',stop:'■ Тўхтатиш',ready:'Овоз ёзишга тайёр',recording:'Овоз ёзилмоқда…',recorded:'Ёзилди. ▶️ босиб эшитиб кўринг.',again:'Қайта ёзиш',remove:'Ўчириш',denied:'Микрофонга рухсат берилмади',unsupported:'Бу браузерда овоз ёзиш ишламайди. Аудио файл танланг.',fallback:'Аудио файл танлаш'},
 ru:{record:'🎙 Записать голос',stop:'■ Остановить',ready:'Готово к записи',recording:'Идёт запись…',recorded:'Записано. Нажмите ▶️ для прослушивания.',again:'Записать заново',remove:'Удалить',denied:'Нет доступа к микрофону',unsupported:'Запись голоса не поддерживается. Выберите аудиофайл.',fallback:'Выбрать аудиофайл'}
};
const t=k=>(TXT[LANG()]||TXT.uz_lat)[k]||k;
function mimeChoice(){
 const cand=['audio/mp4','audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus'];
 if(!window.MediaRecorder)return '';
 for(const m of cand)try{if(MediaRecorder.isTypeSupported&&MediaRecorder.isTypeSupported(m))return m}catch{}
 return '';
}
function extFor(m){m=String(m||'').toLowerCase();if(m.includes('mp4'))return'm4a';if(m.includes('ogg'))return'ogg';if(m.includes('wav'))return'wav';if(m.includes('mpeg'))return'mp3';return'webm'}
function enhance(input){
 if(input.dataset.voiceEnhanced)return;input.dataset.voiceEnhanced='1';input.removeAttribute('capture');input.setAttribute('accept','audio/*,.m4a,.mp3,.wav,.aac,.ogg,.webm');
 const ok=!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia&&window.MediaRecorder&&window.DataTransfer);
 const box=document.createElement('div');box.className='voice-recorder';
 const row=document.createElement('div');row.className='voice-recorder-row';
 const recBtn=document.createElement('button');recBtn.type='button';recBtn.className='voice-rec-btn';recBtn.textContent=t('record');
 const timer=document.createElement('span');timer.className='voice-rec-time';timer.textContent='00:00';
 const status=document.createElement('span');status.className='voice-rec-status';status.textContent=t('ready');
 const preview=document.createElement('audio');preview.className='voice-preview';preview.controls=true;preview.preload='metadata';
 const acts=document.createElement('div');acts.className='voice-rec-actions';
 const again=document.createElement('button');again.type='button';again.className='voice-mini';again.textContent=t('again');
 const remove=document.createElement('button');remove.type='button';remove.className='voice-mini';remove.textContent=t('remove');
 acts.append(again,remove);row.append(recBtn,timer,status);box.append(row,preview,acts);input.insertAdjacentElement('afterend',box);
 let recorder=null,stream=null,chunks=[],tick=null,startAt=0,objUrl='';
 const form=input.closest('form');
 const submits=()=>form?[...form.querySelectorAll('button[type="submit"],input[type="submit"],button:not([type])')]:[];
 function lock(v){submits().forEach(b=>b.disabled=!!v)}
 function clock(){let s=Math.floor((Date.now()-startAt)/1000),m=Math.floor(s/60);timer.textContent=String(m).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}
 function clearStream(){try{stream&&stream.getTracks().forEach(x=>x.stop())}catch{}stream=null}
 function clearCurrent(){input.value='';if(objUrl){URL.revokeObjectURL(objUrl);objUrl=''}preview.removeAttribute('src');preview.classList.remove('show');acts.classList.remove('show');timer.textContent='00:00';status.textContent=t('ready')}
 async function start(){
  if(!ok)return;
  clearCurrent();
  try{
   stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
   const mime=mimeChoice(),opt=mime?{mimeType:mime}:undefined;recorder=new MediaRecorder(stream,opt);chunks=[];
   recorder.ondataavailable=e=>{if(e.data&&e.data.size)chunks.push(e.data)};
   recorder.onstop=()=>{clearInterval(tick);tick=null;clearStream();lock(false);recBtn.classList.remove('recording');recBtn.textContent=t('record');const mt=recorder.mimeType||mime||'audio/webm';const blob=new Blob(chunks,{type:mt});if(!blob.size){status.textContent=t('ready');return}const file=new File([blob],'voice-'+Date.now()+'.'+extFor(mt),{type:mt,lastModified:Date.now()});const dt=new DataTransfer();dt.items.add(file);input.files=dt.files;objUrl=URL.createObjectURL(blob);preview.src=objUrl;preview.classList.add('show');acts.classList.add('show');status.textContent=t('recorded')};
   recorder.start(250);startAt=Date.now();clock();tick=setInterval(clock,500);lock(true);recBtn.classList.add('recording');recBtn.textContent=t('stop');status.textContent=t('recording');
  }catch(err){clearStream();lock(false);status.textContent=t('denied')}
 }
 function stop(){if(recorder&&recorder.state==='recording')recorder.stop()}
 recBtn.onclick=()=>recorder&&recorder.state==='recording'?stop():start();
 again.onclick=()=>start();
 remove.onclick=()=>clearCurrent();
 if(ok){input.classList.add('voice-hidden-input')}else{recBtn.style.display='none';timer.style.display='none';status.textContent=t('unsupported');input.classList.add('voice-fallback')}
 if(form)form.addEventListener('reset',()=>setTimeout(clearCurrent,0));
}
function run(){document.querySelectorAll('input[type="file"][name="audio"]').forEach(enhance)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',run);else run();window.addEventListener('pageshow',run);
})();</script>`;
