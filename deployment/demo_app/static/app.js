document.addEventListener('submit',event=>{const form=event.target;if(form.dataset.confirm&&!confirm(form.dataset.confirm)){event.preventDefault();return}const button=form.querySelector('[data-loading]');if(button){button.disabled=true;button.textContent=button.dataset.loading}});
const preloader=document.getElementById('app-preloader');
const shownAt=performance.now();
window.addEventListener('load',()=>{window.setTimeout(()=>{if(preloader){preloader.classList.add('preloader-done');window.setTimeout(()=>preloader.remove(),500)}},Math.max(0,360-(performance.now()-shownAt)))});
document.querySelectorAll('[data-auto-dialog]').forEach(dialog=>{if(typeof dialog.showModal==='function')dialog.showModal();});
document.querySelectorAll('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
document.querySelectorAll('[data-motion-toggle]').forEach(button=>button.addEventListener('click',()=>{const paused=document.body.classList.toggle('motion-paused');button.setAttribute('aria-pressed',String(paused));button.textContent=paused?'Resume animation':'Pause animation'}));
document.querySelectorAll('[data-filter-select]').forEach(input=>input.addEventListener('input',()=>{const select=document.getElementById(input.dataset.filterSelect);const query=input.value.toLocaleLowerCase();Array.from(select.options).forEach(option=>{option.hidden=!!option.value&&!option.text.toLocaleLowerCase().includes(query);});}));
document.querySelectorAll('[data-filter-table]').forEach(input=>input.addEventListener('input',()=>{const query=input.value.toLocaleLowerCase();document.getElementById(input.dataset.filterTable).querySelectorAll('tbody tr').forEach(row=>{row.hidden=!row.textContent.toLocaleLowerCase().includes(query);});}));
