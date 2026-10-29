(() => {
  const panel=document.getElementById('workspace-guide');if(!panel)return;
  const launcher=document.getElementById('workspace-guide-launcher'), close=document.getElementById('workspace-guide-close'), log=document.getElementById('workspace-guide-log'), prompts=document.getElementById('workspace-guide-prompts'), form=document.getElementById('workspace-guide-form'), input=document.getElementById('workspace-guide-input');
  let loaded=false,busy=false;
  function append(text,kind,links=[]){
    const bubble=document.createElement('div');bubble.className='guide-message '+kind;bubble.textContent=text;
    if(links.length){const actions=document.createElement('div');actions.className='guide-links';for(const link of links){if(typeof link.href!=='string'||!/^\/(?!\/)/.test(link.href))continue;const a=document.createElement('a');a.href=link.href;a.textContent=link.label+' →';actions.append(a);}bubble.append(actions);}
    log.append(bubble);while(log.children.length>30)log.firstElementChild.remove();log.scrollTop=log.scrollHeight;
  }
  async function send(message){
    if(busy||!message.trim())return;busy=true;input.value='';form.querySelector('button').disabled=true;append(message,'guide-question');
    const status=document.createElement('div');status.className='guide-typing';status.textContent='Looking up workspace help…';log.append(status);log.scrollTop=log.scrollHeight;
    try{const response=await fetch('/api/assistant/chat',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({message,csrf:panel.dataset.csrf})});if(!response.ok)throw Error(response.status===401?'Please sign in again to use the guide.':'The guide could not respond. Please try again.');const data=await response.json();status.remove();append(data.message,'guide-reply',data.links||[]);}catch(error){status.remove();append(error.message||'Connection unavailable. Please try again.','guide-reply');}finally{busy=false;form.querySelector('button').disabled=false;}
  }
  async function open(){panel.hidden=false;launcher.setAttribute('aria-expanded','true');input.focus();if(loaded)return;
    try{const response=await fetch('/api/assistant/menu',{cache:'no-store',credentials:'same-origin'});if(!response.ok)throw Error();const data=await response.json();for(const text of data.quick_prompts){const button=document.createElement('button');button.type='button';button.textContent=text;button.addEventListener('click',()=>send(text));prompts.append(button);}loaded=true;}catch(_){append('You can type a navigation question below.','guide-reply');}
  }
  function hide(){panel.hidden=true;launcher.setAttribute('aria-expanded','false');launcher.focus();}
  launcher.addEventListener('click',()=>panel.hidden?open():hide());close.addEventListener('click',hide);panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();hide();}});form.addEventListener('submit',event=>{event.preventDefault();send(input.value.trim());});
})();
