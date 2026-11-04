const judgeNotice = document.querySelector('[data-judge-posts]');

if (judgeNotice) {
  const allowedPaths = new Set(judgeNotice.dataset.judgePosts.split(' '));
  for (const form of document.forms) {
    if (form.method !== 'post' || allowedPaths.has(new URL(form.action).pathname)) continue;
    for (const button of form.querySelectorAll('button[type="submit"], button:not([type]), input[type="submit"]')) {
      button.disabled = true;
      button.dataset.judgeDisabled = '';
      button.title = 'Sample records are read-only in judge access.';
    }
  }
}
