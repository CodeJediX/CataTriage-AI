// Send originals in bounded requests; the final form contains upload IDs only.
if (document.body.dataset.cloudUploads === 'true') {
  document.addEventListener('submit', async event => {
    const form = event.target;
    const inputs = [...form.querySelectorAll('input[type="file"]')];
    const selected = inputs.flatMap(input => [...input.files].map(file => ({input, file})));
    if (!selected.length) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const button = form.querySelector('button[type="submit"],button:not([type])');
    const originalText = button?.textContent;
    const status = document.createElement('p');
    status.setAttribute('role', 'status');
    status.className = 'notice';
    form.append(status);
    form.inert = true;
    try {
      if (selected.length > 12) throw new Error('Select at most 12 images.');
      const csrf = form.elements.namedItem('csrf').value;
      const action = new URL(form.action).pathname;
      const pathCase = action.match(/^\/cases\/([^/]+)\/analysis$/);
      const target = pathCase ? pathCase[1] : (form.elements.namedItem('case_id')?.value || form.elements.namedItem('username')?.value || '');
      const ids = [];
      for (let position = 0; position < selected.length; position++) {
        const {input, file} = selected[position];
        if (file.size > 8 * 1024 * 1024) throw new Error('Each image must be 8 MB or smaller.');
        status.textContent = `Uploading image ${position + 1} of ${selected.length}…`;
        const response = await fetch('/uploads/prepare', {
          method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
          body: JSON.stringify({action, target, field: input.name, name: file.name, size: file.size})
        });
        if (!response.ok) throw new Error('Could not start the upload. Check your sign-in and try again.');
        const upload = await response.json();
        for (let offset = 0, index = 0; offset < file.size; offset += upload.chunk_size, index++) {
          const result = await fetch(`/uploads/${upload.id}/chunks/${index}`, {
            method: 'POST', headers: {'Content-Type': 'application/octet-stream', 'X-CSRF-Token': csrf},
            body: file.slice(offset, offset + upload.chunk_size)
          });
          if (!result.ok) throw new Error('The upload was interrupted. Please select the image again.');
        }
        ids.push(upload.id);
      }
      inputs.forEach(input => { input.disabled = true; });
      form.querySelector('input[name="cloud_uploads"]')?.remove();
      const hidden = document.createElement('input');
      hidden.type = 'hidden'; hidden.name = 'cloud_uploads'; hidden.value = JSON.stringify(ids);
      form.append(hidden);
      status.textContent = 'Images uploaded. Checking and analysing…';
      if (button) { button.disabled = true; button.textContent = 'Checking and analysing…'; }
      HTMLFormElement.prototype.submit.call(form);
    } catch (error) {
      form.inert = false;
      status.textContent = error.message || 'Upload failed. Please try again.';
      if (button) { button.disabled = false; button.textContent = originalText; }
    }
  }, true);
}
